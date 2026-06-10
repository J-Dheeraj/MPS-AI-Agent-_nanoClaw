"""Export each approved feedback record once as a structured Hermes batch."""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .database import FeedbackEntry, SessionLocal
from .services.redaction import scan


def export(output_path: str) -> int:
    db = SessionLocal()
    try:
        rows = (
            db.query(FeedbackEntry)
            .filter(
                FeedbackEntry.status == "approved",
                FeedbackEntry.exported_at.is_(None),
            )
            .order_by(FeedbackEntry.validated_at.asc())
            .all()
        )
        if not rows:
            print("Nothing to export: no newly approved feedback.")
            return 1

        dirty = []
        entries = []
        for row in rows:
            findings = (
                scan(row.agency_code or "")
                + scan(row.incorrect_claim or "")
                + scan(row.correct_answer or "")
                + scan(row.source_title or "")
            )
            if findings:
                dirty.append((row.id, sorted({kind for kind, _ in findings})))
                continue
            if not row.source_title or not row.source_url or not row.effective_date:
                dirty.append((row.id, ["missing_source_metadata"]))
                continue
            entries.append(
                {
                    "feedback_id": row.id,
                    "agency": row.agency_code,
                    "incorrect_claim": row.incorrect_claim,
                    "correct_answer": row.correct_answer,
                    "source": {
                        "title": row.source_title,
                        "url": row.source_url,
                        "effective_date": row.effective_date,
                    },
                    "validated_by": row.validated_by,
                    "validated_at": row.validated_at.isoformat()
                    if row.validated_at
                    else None,
                }
            )

        if dirty:
            print("ABORT: unsafe or incomplete approved feedback. Nothing was exported.")
            for feedback_id, finding_types in dirty:
                print(f"  feedback {feedback_id}: {', '.join(finding_types)}")
            return 1

        batch_id = str(uuid.uuid4())
        exported_at = datetime.now(timezone.utc)
        payload = {
            "schema_version": 1,
            "batch_id": batch_id,
            "exported_at": exported_at.isoformat(),
            "entries": entries,
        }

        output = Path(os.path.expanduser(output_path))
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.{batch_id}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, output)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        for row in rows:
            row.exported_at = exported_at
            row.export_batch_id = batch_id
        db.commit()
        print(f"Exported {len(entries)} corrections in batch {batch_id} to {output}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    target = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "~/mps-hermes-agent/feedback-batch.json"
    )
    sys.exit(export(target))
