"""Load cryptographically manifested, human-approved policy rules."""

import base64
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

VALID_AGENCIES = {"HDB", "CPF", "MSF", "MOH", "MOM", "ICA", "GENERAL"}
MAX_RULES = 100
MAX_RULE_BYTES = 65_536
# Total character budget for the policy context block sent to the model.
# At ~4 chars/token this is roughly 4 000 tokens — enough for ~25 detailed rules
# while leaving headroom for the letter draft in a 8k-token model (V-H6).
# Override with POLICY_CONTEXT_BUDGET env var (characters).
MAX_CONTEXT_CHARS = int(__import__('os').getenv('POLICY_CONTEXT_BUDGET', '16000'))


class PolicyStoreError(RuntimeError):
    pass


def _policy_dir() -> Path:
    default = Path(__file__).resolve().parents[2] / "policy" / "active"
    return Path(os.getenv("POLICY_DIR", str(default))).resolve()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_source(source: dict) -> None:
    parsed = urlparse(str(source.get("url", "")))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "gov.sg" or host.endswith(".gov.sg")):
        raise PolicyStoreError("Policy source must be an HTTPS gov.sg URL")
    if not str(source.get("title", "")).strip():
        raise PolicyStoreError("Policy source title is missing")
    try:
        date.fromisoformat(str(source.get("effective_date", "")))
    except ValueError as exc:
        raise PolicyStoreError("Policy effective date is invalid") from exc
    effective_to = source.get("effective_to")
    if effective_to is not None:
        try:
            date.fromisoformat(str(effective_to))
        except ValueError as exc:
            raise PolicyStoreError("Policy effective_to date is invalid") from exc


def _verify_manifest_signature(manifest_path: Path, manifest_bytes: bytes) -> None:
    """Fail-closed Ed25519 verification of the policy manifest.

    When POLICY_PUBLIC_KEY is configured, the manifest MUST carry a valid
    signature (manifest.json.sig) from the trusted release key. This is the
    control that stops a manifest forged by someone with only filesystem
    access: recomputing the hashes is not enough — they would also need the
    managed private signing key. If no public key is configured the check is
    skipped (development only); production startup requires it to be set.
    """
    public_key_path = os.getenv("POLICY_PUBLIC_KEY", "").strip()
    if not public_key_path:
        return  # dev mode: signing not enforced

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature

    try:
        public_key = serialization.load_pem_public_key(Path(public_key_path).read_bytes())
    except Exception as exc:  # noqa: BLE001 - surfaced as a policy error
        raise PolicyStoreError("POLICY_PUBLIC_KEY could not be loaded") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise PolicyStoreError("POLICY_PUBLIC_KEY must be an Ed25519 public key")

    sig_path = manifest_path.with_name("manifest.json.sig")
    if not sig_path.is_file():
        raise PolicyStoreError("Policy manifest is not signed (manifest.json.sig missing)")
    sidecar = json.loads(sig_path.read_text(encoding="utf-8"))
    if sidecar.get("schema_version") != 1 or sidecar.get("algorithm") != "ed25519":
        raise PolicyStoreError("Unsupported manifest signature format")
    signature = sidecar.get("signature")
    if not isinstance(signature, str) or not signature:
        raise PolicyStoreError("Manifest signature is missing")
    try:
        public_key.verify(base64.b64decode(signature), manifest_bytes)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise PolicyStoreError("Manifest signature failed verification") from exc


def load_policy_context(agency: str) -> tuple[str, list[dict], str | None]:
    agency = agency.strip().upper()
    if agency not in VALID_AGENCIES:
        raise PolicyStoreError(f"Unsupported agency: {agency}")

    root = _policy_dir()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return "", [], None
    manifest_bytes = manifest_path.read_bytes()
    _verify_manifest_signature(manifest_path, manifest_bytes)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    entries = manifest.get("rules")
    if manifest.get("schema_version") != 1 or not isinstance(entries, list):
        raise PolicyStoreError("Unsupported policy manifest")
    if len(entries) > MAX_RULES:
        raise PolicyStoreError("Policy manifest exceeds the rule limit")

    today = date.today()

    # ── Pass 1: collect all matching rules (validity + agency filter) ────────
    candidate_rules = []
    for entry in entries:
        file_name = str(entry.get("file", ""))
        if Path(file_name).name != file_name or not file_name.endswith(".json"):
            raise PolicyStoreError("Unsafe policy file name")
        path = (root / file_name).resolve()
        if path.parent != root or not path.is_file():
            raise PolicyStoreError(f"Policy rule is missing: {file_name}")
        if path.stat().st_size > MAX_RULE_BYTES:
            raise PolicyStoreError(f"Policy rule is too large: {file_name}")
        raw = path.read_bytes()
        if _sha256(raw) != entry.get("sha256"):
            raise PolicyStoreError(f"Policy rule hash mismatch: {file_name}")

        rule = json.loads(raw)
        if rule.get("schema_version") != 1:
            raise PolicyStoreError(f"Unsupported rule schema: {file_name}")
        rule_agency = str(rule.get("agency", "")).upper()
        if rule_agency not in VALID_AGENCIES:
            raise PolicyStoreError(f"Unsupported rule agency: {file_name}")
        source = rule.get("source") or {}
        _validate_source(source)
        effective_from = date.fromisoformat(source["effective_date"])
        # Skip rules not yet in force or not matching this agency
        if effective_from > today or rule_agency not in {agency, "GENERAL"}:
            continue
        # Skip expired rules (effective_to set and already passed)
        effective_to_raw = source.get("effective_to")
        if effective_to_raw:
            if date.fromisoformat(effective_to_raw) < today:
                continue
        statement = str(rule.get("statement", "")).strip()
        if not statement or len(statement) > 4_000:
            raise PolicyStoreError(f"Invalid policy statement: {file_name}")
        rule_id = str(rule.get("rule_id", file_name))
        supersedes = [str(r) for r in rule.get("supersedes", [])]
        candidate_rules.append({
            "rule_id": rule_id,
            "statement": statement,
            "effective_from": effective_from,
            "source": source,
            "supersedes": supersedes,
        })

    # ── Pass 2: remove superseded rules (V-H6) ───────────────────────────────
    # If rule A declares supersedes=[B, C], exclude B and C from context.
    superseded_ids: set = set()
    for cr in candidate_rules:
        superseded_ids.update(cr["supersedes"])
    active_rules = [r for r in candidate_rules if r["rule_id"] not in superseded_ids]

    # ── Pass 3: rank by most-recent effective date first (V-H6) ──────────────
    active_rules.sort(key=lambda r: r["effective_from"], reverse=True)

    # ── Pass 4: enforce token budget (V-H6) ───────────────────────────────────
    context_lines = []
    sources = []
    budget_remaining = MAX_CONTEXT_CHARS
    for cr in active_rules:
        source = cr["source"]
        line = (
            f"[RULE {cr['rule_id']}] {cr['statement']}\n"
            f"Source: {source['title']} | {source['url']} | effective {source['effective_date']}"
        )
        if len(line) > budget_remaining:
            break  # budget exhausted — drop lower-priority rules
        context_lines.append(line)
        sources.append({
            "rule_id": cr["rule_id"],
            "title": source["title"],
            "url": source["url"],
            "effective_date": source["effective_date"],
        })
        budget_remaining -= len(line)

    return "\n\n".join(context_lines), sources, manifest.get("generated_at")
