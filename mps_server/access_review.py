"""Access recertification report (V-C3).

Emits the user/role inventory an approver needs for periodic access review:
every account, its role, active state, lockout status and age. Output is JSON
on stdout so it can be archived as evidence of a completed review.

    python3 -m mps_server.access_review            # human-readable
    python3 -m mps_server.access_review --json      # machine-readable
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from .database import User, SessionLocal


def build_report(db) -> dict:
    now = datetime.now(timezone.utc)
    rows = []
    for user in db.query(User).order_by(User.role, User.username).all():
        created = user.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).days if created else None
        locked = bool(user.locked_until and user.locked_until.replace(
            tzinfo=timezone.utc) > now) if user.locked_until else False
        rows.append({
            "username": user.username,
            "role": user.role,
            "is_active": bool(user.is_active),
            "locked": locked,
            "failed_logins": user.failed_logins,
            "account_age_days": age_days,
        })
    by_role = {}
    for r in rows:
        by_role[r["role"]] = by_role.get(r["role"], 0) + 1
    return {
        "generated_at": now.isoformat(),
        "total_users": len(rows),
        "by_role": by_role,
        "inactive": [r["username"] for r in rows if not r["is_active"]],
        "users": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        report = build_report(db)
    finally:
        db.close()
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(f"Access review — {report['generated_at']}")
    print(f"Total users: {report['total_users']}  by role: {report['by_role']}")
    if report["inactive"]:
        print(f"Inactive accounts (review for removal): {', '.join(report['inactive'])}")
    print(f"{'username':20s} {'role':10s} {'active':7s} {'locked':7s} {'age(d)':6s}")
    for r in report["users"]:
        print(f"{r['username']:20s} {r['role']:10s} "
              f"{str(r['is_active']):7s} {str(r['locked']):7s} {str(r['account_age_days']):6s}")


if __name__ == "__main__":
    main()
