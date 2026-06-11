"""add pending_totp_secret, mfa_enabled, recovery_codes to users

Revision ID: 20260612_01
Revises: 20260611_01
Create Date: 2026-06-12

V3-C1: Two-phase MFA enrolment. pending_totp_secret holds the unconfirmed
secret during /mfa/enroll; mfa_enabled is set only on /mfa/activate success.
This prevents an interrupted enrolment from locking the user out.
recovery_codes stores bcrypt hashes of one-time fallback codes.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260612_01"
down_revision = "20260611_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pending_totp_secret", sa.String(), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False,
                                      server_default="false"))
    op.add_column("users", sa.Column("recovery_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "recovery_codes")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "pending_totp_secret")
