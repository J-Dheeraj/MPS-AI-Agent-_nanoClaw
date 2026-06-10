"""Load cryptographically manifested, human-approved policy rules."""

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

VALID_AGENCIES = {"HDB", "CPF", "MSF", "MOH", "MOM", "ICA", "GENERAL"}
MAX_RULES = 100
MAX_RULE_BYTES = 65_536


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


def load_policy_context(agency: str) -> tuple[str, list[dict], str | None]:
    agency = agency.strip().upper()
    if agency not in VALID_AGENCIES:
        raise PolicyStoreError(f"Unsupported agency: {agency}")

    root = _policy_dir()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return "", [], None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("rules")
    if manifest.get("schema_version") != 1 or not isinstance(entries, list):
        raise PolicyStoreError("Unsupported policy manifest")
    if len(entries) > MAX_RULES:
        raise PolicyStoreError("Policy manifest exceeds the rule limit")

    context_lines = []
    sources = []
    today = date.today()
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
        effective = date.fromisoformat(source["effective_date"])
        if effective > today or rule_agency not in {agency, "GENERAL"}:
            continue
        statement = str(rule.get("statement", "")).strip()
        if not statement or len(statement) > 4_000:
            raise PolicyStoreError(f"Invalid policy statement: {file_name}")
        rule_id = str(rule.get("rule_id", file_name))
        context_lines.append(
            f"[RULE {rule_id}] {statement}\n"
            f"Source: {source['title']} | {source['url']} | effective {source['effective_date']}"
        )
        sources.append(
            {
                "rule_id": rule_id,
                "title": source["title"],
                "url": source["url"],
                "effective_date": source["effective_date"],
            }
        )

    return "\n\n".join(context_lines), sources, manifest.get("generated_at")
