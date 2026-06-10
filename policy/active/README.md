# Active Policy Store

This directory is populated only by `MPS-AI-Agent-Hermes/promote_approved.py`.

The server ignores loose files. It loads policy rules only when `manifest.json`
lists each rule with its SHA-256 hash, and each rule contains a reviewed HTTPS
`gov.sg` source and effective date.

Do not edit generated rule files or the manifest by hand. A changed file hash
causes policy retrieval to fail closed.
