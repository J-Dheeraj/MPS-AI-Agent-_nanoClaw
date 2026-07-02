# Release drill fixtures (non-production)

Sample inputs for the **worked-example `v*` release drill** (2026-07-02 v11
review, Important #2). Together with throwaway drill signing keys stored as the
`RELEASE_SIGNING_KEY_PEM` / `RELEASE_PUBLIC_KEY_PEM` repository secrets, and the
repo variables `RELEASE_POLICY_DIR` / `RELEASE_EVAL_PATH` pointing here, a
`v*-drill` tag exercises the full fail-closed release gate for real:
`--require-eval`, `--require-signed`, `--require-complete`, plus in-CI signature
verification and artifact upload.

**What the drill proves:** the release *mechanism* — trigger, gates, signing,
verification, evidence artifacts — executed end to end.

**What it does NOT prove:** production evidence. `eval.json` here is a labeled
sample, `policy/manifest.json` is a fixture, and the drill keys are throwaway.
A production release replaces all three: prod-model eval output, the active
signed policy manifest, and production keys enrolled under two-person control
(see `../RELEASE_PROCESS.md` and `../../runbooks/key-lifecycle.md`).
