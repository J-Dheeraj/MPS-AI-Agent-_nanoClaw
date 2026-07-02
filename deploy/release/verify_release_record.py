#!/usr/bin/env python3
"""Independently verify a signed NanoClaw release record (2026-07-02 review,
Critical #2).

Recanonicalises release-record.json exactly as the generator did (sorted keys,
compact separators) and verifies release-record.json.sig with the Ed25519 public
key at RELEASE_PUBLIC_KEY. Exit 0 = signature valid; non-zero otherwise. This is
the executable verification path a third party (or CI) runs so release signing
cannot become ceremonial.

Usage:
  RELEASE_PUBLIC_KEY=release-pub.pem \\
    python3 deploy/release/verify_release_record.py [record.json] [record.json.sig]
"""
import base64
import json
import os
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    record_path = argv[0] if argv else "release-record.json"
    sig_path = argv[1] if len(argv) > 1 else record_path + ".sig"

    pub_path = os.getenv("RELEASE_PUBLIC_KEY", "").strip()
    if not pub_path:
        print("RELEASE_PUBLIC_KEY is not set (path to the Ed25519 public-key PEM)",
              file=sys.stderr)
        return 2
    if not os.path.isfile(record_path) or not os.path.isfile(sig_path):
        print(f"missing record ({record_path}) or signature ({sig_path})",
              file=sys.stderr)
        return 2

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub = serialization.load_pem_public_key(open(pub_path, "rb").read())
    if not isinstance(pub, Ed25519PublicKey):
        print("RELEASE_PUBLIC_KEY must be an Ed25519 public key", file=sys.stderr)
        return 2

    record = json.load(open(record_path, encoding="utf-8"))
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = base64.b64decode(open(sig_path, encoding="utf-8").read().strip())

    try:
        pub.verify(signature, canonical)
    except InvalidSignature:
        print("SIGNATURE INVALID: the release record does not match its "
              "signature — it was tampered with or signed by a different key.",
              file=sys.stderr)
        return 1
    print(f"signature OK: {record_path} verified against {pub_path} "
          f"(commit {record.get('commit', '?')[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
