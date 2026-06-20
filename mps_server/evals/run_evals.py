"""Model-executed evaluation runner (C4).

Runs the labelled datasets through the DEPLOYED model (Ollama) using the same
build_draft_messages + generation path the server uses, scores each output with
the deterministic scorers, and checks the results against THRESHOLDS. Exits
non-zero on any breach so it can gate a release.

Usage (on a host where Ollama serves the production model):
    python3 -m mps_server.evals.run_evals

Requires OLLAMA_URL/OLLAMA_MODEL to point at the deployed model. If Ollama is
unreachable the runner reports that and exits 2 (not a pass).
"""
import asyncio
import sys

import httpx

from ..services.ollama_client import (
    build_draft_messages, OLLAMA_URL, OLLAMA_MODEL, Priority, llm_queue,
)
from . import datasets, scorers
from .thresholds import THRESHOLDS


async def _draft(case) -> str:
    messages = build_draft_messages(
        case_type=case["case_type"], agency=case["agency"], notes=case["notes"],
        policy_context=case.get("policy_context"))
    out = ""
    async for chunk in llm_queue.run(messages, priority=Priority.NORMAL):
        out += chunk
    return out


def _ollama_reachable() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


async def main() -> int:
    if not _ollama_reachable():
        print(f"SKIP: Ollama not reachable at {OLLAMA_URL}; cannot evaluate "
              f"the deployed model.")
        return 2

    print(f"Evaluating model {OLLAMA_MODEL} at {OLLAMA_URL}\n")
    results = {"injection": [], "pii": [], "groundedness": [], "citation": []}

    for case in datasets.INJECTION_CASES:
        out = await _draft(case)
        results["injection"].append(
            scorers.score_injection(out, case["forbidden_substrings"])["passed"])
    for case in datasets.PII_CASES:
        out = await _draft(case)
        results["pii"].append(scorers.score_pii_leak(out)["passed"])
    for case in datasets.GROUNDING_CASES:
        out = await _draft(case)
        results["groundedness"].append(
            scorers.score_groundedness(out, case["policy_context"])["passed"])
    for case in datasets.CITATION_CASES:
        out = await _draft(case)
        results["citation"].append(
            scorers.score_citations(out, case["policy_context"])["passed"])

    def rate(key):
        vals = results[key]
        return sum(vals) / len(vals) if vals else 1.0

    measured = {
        "injection_pass_rate": rate("injection"),
        "pii_pass_rate": rate("pii"),
        "groundedness_pass_rate": rate("groundedness"),
        "citation_precision": rate("citation"),
    }

    breaches = []
    for metric, threshold in THRESHOLDS.items():
        got = measured[metric]
        status = "PASS" if got >= threshold else "FAIL"
        print(f"  {metric:24s} {got:.2f}  (>= {threshold:.2f})  {status}")
        if got < threshold:
            breaches.append(metric)

    print()
    if breaches:
        print(f"FAILED thresholds: {', '.join(breaches)}")
        return 1
    print("All model-evaluation thresholds met.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
