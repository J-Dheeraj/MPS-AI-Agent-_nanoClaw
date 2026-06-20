"""I4 prompt-hash provenance + I5 correlation IDs."""
import re


def test_prompt_sha256_is_stable_content_hash():
    from mps_server.services.ollama_client import (
        PROMPT_SHA256, LETTER_SYSTEM, REAPPEAL_SYSTEM)
    import hashlib
    assert re.fullmatch(r"[0-9a-f]{64}", PROMPT_SHA256)
    expected = hashlib.sha256(
        (LETTER_SYSTEM + REAPPEAL_SYSTEM).encode("utf-8")).hexdigest()
    assert PROMPT_SHA256 == expected


def test_generation_meta_includes_provenance_and_correlation():
    # The draft handler writes prompt_sha256 + correlation_id into the meta dict.
    src = (__import__("pathlib").Path(__file__).resolve().parents[1]
           / "mps_server/routers/letters_router.py").read_text()
    assert '"prompt_sha256": PROMPT_SHA256' in src
    assert '"correlation_id": _cid' in src


def test_correlation_id_round_trips_through_http(monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "x" * 32)
    from fastapi.testclient import TestClient
    from mps_server import main as m
    client = TestClient(m.app, base_url="http://localhost")
    # Supplied id is echoed back.
    r = client.get("/health/live", headers={"X-Correlation-ID": "test-cid-123"})
    assert r.headers.get("X-Correlation-ID") == "test-cid-123"
    # Absent id is generated.
    r2 = client.get("/health/live")
    assert re.fullmatch(r"[0-9a-f]{32}", r2.headers.get("X-Correlation-ID", ""))
