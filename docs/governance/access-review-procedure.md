# Access Review Procedure

**Owner:** _<Account Administrator — to be assigned>_
**Last reviewed:** 2026-06-11
**Cadence:** Monthly, and on any volunteer/vetter roster change.

## Purpose

Confirm that only current, authorised volunteers, vetters, and administrators
hold accounts, with the correct role, and that dormant or unnecessary accounts
are removed.

## Procedure

1. Generate the recertification report:
   ```
   python3 -m mps_server.access_review --json > access-review-$(date +%F).json
   ```
2. For each account, confirm with the MP's office roster:
   - the person is still an active volunteer/vetter/admin;
   - the **role** is correct (least privilege — volunteers must not hold vetter
     or admin roles);
   - the account is not unexpectedly **locked** (repeated lockouts may indicate
     credential attacks — investigate).
3. For any account that should no longer have access, deactivate it
   (`is_active = false`). Deactivation causes existing tokens to fail the
   revocation/active-user check on the next request.
4. File the report and the sign-off as evidence of a completed review.

## Sign-off

| Reviewer | Date | Accounts reviewed | Actions taken |
|---|---|---|---|
| | | | |

## Notes

- The report flags inactive accounts explicitly for removal consideration.
- There is no self-service registration in production (`/auth/signup` disabled);
  accounts are created by an administrator via `/auth/register`.
