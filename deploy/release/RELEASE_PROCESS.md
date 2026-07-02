# Production release process (v* tags)

Status: repeatable procedure (2026-07-02 review, Important #1). This is the exact
path for cutting a production release — and the recipe for the reviewer's
"operational proof sprint". Every gate below is **fail-closed**: a missing input
blocks the release rather than shipping without evidence.

## What a `v*` tag enforces

On `git push origin v<semver>`, the `release-record` CI job runs the generator
with three flags plus verification:

| Gate | Flag | Fails when |
|------|------|-----------|
| Model evaluation | `--require-eval` | `eval.json` absent or `model_eval` is `not_executed` |
| Signing | `--require-signed` | `RELEASE_SIGNING_KEY` not configured |
| Completeness | `--require-complete` | any governance field is null (commit, model, prompt, validator, schema, **policy manifest**, dependency audit, SBOM) |
| Verification | `verify_release_record.py` | the signature does not verify against `RELEASE_PUBLIC_KEY` |

## Before tagging — prepare the four inputs

### 1. Model-evaluation result (`eval.json`)
Run the evaluation **on the trusted production Ollama host** against the exact
model that will serve production:

```
RUN_MODEL_EVALS=1 OLLAMA_URL=http://<prod-host>:11434 OLLAMA_MODEL=<prod-model> \
  python3 -m mps_server.evals.run_evals
```

All thresholds (injection / PII / groundedness / citation precision **and
recall**) are 1.0 — the runner exits non-zero on any breach. On success, record
the result for the release job:

```json
{ "result": "pass", "model": "<prod-model>", "run_at": "<iso-timestamp>" }
```

Supply it to the generator via `--eval-result eval.json` (the release workflow
reads `eval.json` in the working directory — commit it to the release branch,
attach it via a workflow input, or stage it on the runner before the gate step).

### 2. Active signed policy manifest (`POLICY_DIR`)
`--require-complete` hashes the active policy manifest. Set `POLICY_DIR` in the
release job environment to the directory containing the Ed25519-signed manifest
(`manifest.json`) that production will load. **If `POLICY_DIR` is unset, the
completeness gate fails closed** — this is intentional: a production release
must bind the exact policy snapshot it ships with.

### 3. Release signing keys (repository secrets)
Create an Ed25519 keypair (one-liner in
[`../runbooks/key-lifecycle.md`](../runbooks/key-lifecycle.md), Enrolment
section) under two-person control, then add **the PEM contents** as repository
secrets:

- `RELEASE_SIGNING_KEY_PEM` — private key (used only on tag builds; CI writes it
  to a runner-local file with `umask 077`)
- `RELEASE_PUBLIC_KEY_PEM` — public key (used by the in-CI verification step)

### 4. Green prerequisites
The ordinary push gates (pip-audit, SBOM+grype, gitleaks, PostgreSQL
concurrency, promtool) must already be green on the commit being tagged.

## Tagging

```
git tag v1.0.0
git push origin v1.0.0
```

CI generates `release-record.json`, signs it, verifies the signature, and
uploads **both** `release-record.json` and `release-record.json.sig` as the
`release-record` artifact.

## Failure modes (all fail-closed by design)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RELEASE GATE FAILED: model_eval is not present` | no `eval.json` on the runner | run the prod-model eval (step 1) and supply the result |
| `RELEASE GATE FAILED: RELEASE_SIGNING_KEY is not configured` | `RELEASE_SIGNING_KEY_PEM` secret missing | add the secret (step 3) |
| `RELEASE GATE FAILED: critical governance fields are null: policy_manifest_sha256…` | `POLICY_DIR` unset or manifest missing | point `POLICY_DIR` at the active signed manifest (step 2) |
| `SIGNATURE INVALID` in the verify step | record modified after signing, or key mismatch | regenerate; confirm the public/private secrets are the same pair |

## Evidence to retain (attach to the release / audit record)

- `release-record.json` + `release-record.json.sig` (CI artifact)
- the eval runner output from the production host
- the verifier command for auditors:
  `RELEASE_PUBLIC_KEY=release-pub.pem python3 deploy/release/verify_release_record.py release-record.json`
- the CI run URL showing all gates green

Executing this process once, end to end, with real production inputs **is** the
release-tag drill the 2026-07-02 review lists as Critical #1.
