# Release record (signed provenance)

`generate_release_record.py` emits a single canonical JSON record that binds, per
release, the things the architecture reviews repeatedly asked to be tied
together (Governance Gaps / Critical #4):

- source `commit`
- `model`, `prompt_version`, `prompt_sha256`, `validator_version`, `schema_revision`
- `policy_manifest_sha256` (the active signed policy manifest)
- `dependency_audit` status and `sbom_sha256`
- `model_eval` result

It is signed with Ed25519 (`RELEASE_SIGNING_KEY`, same primitive as the audit
checkpoint signer) so a release is attributable and tamper-evident.

## Generate (CI does this on every push)
```
python3 deploy/release/generate_release_record.py \
    --pip-audit pip-audit.json --sbom sbom-python.json \
    --eval-result eval.json --out release-record.json
```
Unsigned in dev; set `RELEASE_SIGNING_KEY` (Ed25519 PEM) to sign → also writes
`release-record.json.sig`.

## Verify the signature
```
python3 - <<'PY'
import base64, json
from cryptography.hazmat.primitives import serialization
rec = open("release-record.json","rb").read()
# canonicalise exactly as the generator did:
import json as _j; canon=_j.dumps(_j.loads(rec),sort_keys=True,separators=(",",":")).encode()
pub = serialization.load_pem_public_key(open("release-pub.pem","rb").read())
pub.verify(base64.b64decode(open("release-record.json.sig").read().strip()), canon)
print("signature OK")
PY
```

## Release gate (Critical #1)
On a `v*` tag, CI runs the generator with `--require-eval`, which **fails the
build if `model_eval` is `not_executed`/absent**. This enforces "every
production release must include a model-evaluation result tied to the exact
model/prompt/policy/commit" — the eval must be run on the production model (on a
trusted runner) and its result passed via `--eval-result` before a release tag
can succeed. Producing that eval result is the operational step that remains.
