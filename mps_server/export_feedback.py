"""
Export approved feedback corrections to Hermes — structured, fail-closed.

Replaces the old grep-over-free-text-markdown export. Source of truth is the
anonymised FeedbackEntry table (status='approved'), which carries NO case or
resident linkage. Every field is additionally passed through the structured
redactor (services/redaction.py) as defence-in-depth.

If any field still contains detectable PII after redaction, the export ABORTS
(fail closed) and reports which entries are dirty — nothing is written.

Usage:
    python3 -m mps_server.export_feedback [output_path]
Default output: ~/mps-hermes-agent/feedback-input.md
Exit 0 = exported, 1 = aborted (PII found or nothing to export).
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .database import FeedbackEntry, SessionLocal
from .services.redaction import scan


def export(output_path: str) -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(FeedbackEntry)
            .filter(FeedbackEntry.status == "approved")
            .order_by(FeedbackEntry.validated_at.asc())
            .all()
        )
        if not rows:
            print("Nothing to export: no approved feedback.")
            return 1

        dirty = []
        lines = [
            "# Hermes feedback input (anonymised policy corrections)",
            f"# Exported: {datetime.now(timezone.utc).isoformat()}",
            f"# Source: FeedbackEntry table, status=approved ({len(rows)} entries)",
            "# Structure: agency | wrong | correct  — no case/resident linkage",
            "",
        ]
        for r in rows:
            # Defence-in-depth: these fields are policy text, but scan anyway.
            findings = (
                scan(r.agency_code or "")
                + scan(r.incorrect_claim or "")
                + scan(r.correct_answer or "")
            )
            if findings:
                dirty.append((r.id, [t for t, _ in findings]))
                continue
            lines.append(
                f"- agency: {r.agency_code} | wrong: {r.incorrect_claim} | correct: {r.correct_answer}"
            )

        if dirty:
            print("ABORT — PII detected in approved feedback (fail closed). "
                  "Nothing was exported.")
            for fid, types in dirty:
                print(f"  feedback {fid}: {', '.join(sorted(set(types)))}")
            print("Fix or reject these entries before re-running the export.")
            return 1

        out = Path(os.path.expanduser(output_path))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n")
        print(f"Exported {len(rows)} anonymised corrections to {out}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "~/mps-hermes-agent/feedback-input.md"
    sys.exit(export(target))
