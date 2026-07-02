#!/usr/bin/env python3
"""Signed release record for NanoClaw (2026-06-23 review, Critical #4 + #1).

Every review's "Governance Gaps" asks for a single record that binds the source
commit, the model/prompt/policy/validator identities, the dependency-audit and
SBOM results, and the model-evaluation result — signed, so a release is
attributable and tamper-evident.

This generator collects those values from things already in the repo/CI and
emits a canonical JSON record plus an optional Ed25519 signature. On a release it
is run with --require-eval, which fails if no model-evaluation result is present
— that is the enforced "every production release must include a model-eval
result" gate (Critical #1) without needing the model during ordinary push CI.

Usage:
  python3 deploy/release/generate_release_record.py \\
      [--out release-record.json] [--require-eval] \\
      [--pip-audit pip-audit.json] [--sbom sbom-python.json] \\
      [--eval-result eval.json]

Signing: set RELEASE_SIGNING_KEY to an Ed25519 private-key PEM path to sign;
verify later with RELEASE_PUBLIC_KEY. Unsigned (dev) when unset.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return os.getenv("GITHUB_SHA", "unknown")


def _sha256_file(path: str):
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Ensure the repo root is importable when run as a standalone script
# (python3 deploy/release/...py puts the script dir on sys.path[0], not the root).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _constants() -> dict:
    """Pull provenance identities from the production modules (single source)."""
    out = {}
    try:
        from mps_server.services.ollama_client import (
            PROMPT_VERSION, PROMPT_SHA256, OLLAMA_MODEL)
        out.update(prompt_version=PROMPT_VERSION, prompt_sha256=PROMPT_SHA256,
                   model=OLLAMA_MODEL)
    except Exception:
        out.update(prompt_version=None, prompt_sha256=None, model=None)
    try:
        from mps_server.services.validator import VALIDATOR_VERSION
        out["validator_version"] = VALIDATOR_VERSION
    except Exception:
        out["validator_version"] = None
    try:
        import re
        main_src = open(os.path.join(_repo_root(), "mps_server", "main.py")).read()
        m = re.search(r'EXPECTED_SCHEMA_REVISION\s*=\s*"([^"]+)"', main_src)
        out["schema_revision"] = m.group(1) if m else None
    except Exception:
        out["schema_revision"] = None
    return out


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pip_audit_status(path: str):
    """pip-audit --format json emits [] (or {"dependencies": []}) when clean."""
    if not path or not os.path.isfile(path):
        return None
    try:
        data = json.load(open(path))
        if isinstance(data, dict):
            vulns = data.get("dependencies", data.get("vulnerabilities", []))
        else:
            vulns = data
        found = [d for d in vulns if isinstance(d, dict) and d.get("vulns")]
        return "clean" if not found else f"{len(found)} vulnerable"
    except Exception:
        return "unparseable"


def _eval_result(path: str):
    if not path or not os.path.isfile(path):
        return "not_executed"
    try:
        data = json.load(open(path))
        return data.get("result", data.get("status", "present"))
    except Exception:
        return "present"


def _policy_manifest_sha256():
    policy_dir = os.getenv("POLICY_DIR", "").strip()
    if not policy_dir:
        return None
    for name in ("manifest.json", "policy_manifest.json"):
        p = os.path.join(policy_dir, name)
        if os.path.isfile(p):
            return _sha256_file(p)
    return None


def build_record(args) -> dict:
    c = _constants()
    return {
        "schema_version": 1,
        "kind": "nanoclaw-release-record",
        "commit": _git_commit(),
        "model": c["model"],
        "prompt_version": c["prompt_version"],
        "prompt_sha256": c["prompt_sha256"],
        "validator_version": c["validator_version"],
        "schema_revision": c["schema_revision"],
        "policy_manifest_sha256": _policy_manifest_sha256(),
        "dependency_audit": _pip_audit_status(args.pip_audit),
        "sbom_sha256": _sha256_file(args.sbom),
        "model_eval": _eval_result(args.eval_result),
    }


def canonical_bytes(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(record_bytes: bytes):
    """Sign canonical record bytes with RELEASE_SIGNING_KEY (Ed25519). Reuses the
    same primitive as the audit checkpoint signer. Returns base64 sig or None."""
    path = os.getenv("RELEASE_SIGNING_KEY", "").strip()
    if not path:
        return None
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = serialization.load_pem_private_key(open(path, "rb").read(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("RELEASE_SIGNING_KEY must be an Ed25519 private key")
    return base64.b64encode(key.sign(record_bytes)).decode("ascii")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="release-record.json")
    ap.add_argument("--pip-audit", default="pip-audit.json")
    ap.add_argument("--sbom", default="sbom-python.json")
    ap.add_argument("--eval-result", default="eval.json")
    ap.add_argument("--require-eval", action="store_true",
                    help="fail if no model-evaluation result is present (release gate)")
    ap.add_argument("--require-signed", action="store_true",
                    help="fail if RELEASE_SIGNING_KEY is not configured (release gate)")
    ap.add_argument("--require-complete", action="store_true",
                    help="fail if any critical governance field is null (release gate)")
    args = ap.parse_args(argv)

    record = build_record(args)

    if args.require_eval and record["model_eval"] in (None, "not_executed"):
        print("RELEASE GATE FAILED: model_eval is not present. A production "
              "release must include a model-evaluation result tied to this "
              "commit/model/prompt/policy.", file=sys.stderr)
        return 1

    if args.require_complete:
        critical = ["commit", "model", "prompt_version", "prompt_sha256",
                    "validator_version", "schema_revision",
                    "policy_manifest_sha256", "dependency_audit", "sbom_sha256"]
        missing = [k for k in critical if record.get(k) in (None, "", "unknown")]
        if missing:
            print("RELEASE GATE FAILED: critical governance fields are null: "
                  + ", ".join(missing) + ". A production release record must "
                  "bind every governance identity.", file=sys.stderr)
            return 1

    if args.require_signed and not os.getenv("RELEASE_SIGNING_KEY", "").strip():
        print("RELEASE GATE FAILED: RELEASE_SIGNING_KEY is not configured. A "
              "production release record must be Ed25519-signed so it is "
              "attributable and independently verifiable.", file=sys.stderr)
        return 1

    body = canonical_bytes(record)
    signature = sign(body)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(record, fh, sort_keys=True, indent=2)
    if signature is not None:
        with open(args.out + ".sig", "w", encoding="utf-8") as fh:
            fh.write(signature + "\n")
    print(json.dumps(record, sort_keys=True, indent=2))
    print(f"\nsignature: {'written to ' + args.out + '.sig' if signature else 'UNSIGNED (set RELEASE_SIGNING_KEY)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
