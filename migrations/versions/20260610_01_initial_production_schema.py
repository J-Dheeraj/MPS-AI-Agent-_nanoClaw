"""Initial production schema.

Revision ID: 20260610_01
Revises: None
"""

from alembic import op
import sqlalchemy as sa

revision = "20260610_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("hashed_pw", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("totp_secret", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("mp_approved_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("carried_over", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "residents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("nric_masked", sa.String(), nullable=False, unique=True),
        sa.Column("contact", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "cases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("resident_id", sa.String(), sa.ForeignKey("residents.id"), nullable=False),
        sa.Column("case_type", sa.String(), nullable=False),
        sa.Column("agency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="assigned"),
        sa.Column("parent_case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("is_new_issue", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("urgency", sa.String(), nullable=False, server_default="normal"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("volunteer_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cases_session_status", "cases", ["session_id", "status"])
    op.create_index("ix_cases_volunteer", "cases", ["volunteer_id"])

    op.create_table(
        "letters",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("draft_content", sa.Text(), nullable=True),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("vetter_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("vetted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_letters_case", "letters", ["case_id"])

    op.create_table(
        "feedback_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("logged_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("validated_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("incorrect_claim", sa.Text(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("agency_code", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("source_title", sa.String(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("effective_date", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("validated_at", sa.DateTime(), nullable=True),
        sa.Column("exported_at", sa.DateTime(), nullable=True),
        sa.Column("export_batch_id", sa.String(), nullable=True),
    )
    op.create_index("ix_feedback_status", "feedback_entries", ["status", "exported_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("case_id", sa.String(), nullable=True),
        sa.Column("letter_id", sa.String(), nullable=True),
        sa.Column("letter_version", sa.Integer(), nullable=True),
        sa.Column("client_ip", sa.String(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.String(), nullable=True),
        sa.Column("entry_hash", sa.String(), nullable=True),
        sa.Column("hash_version", sa.Integer(), nullable=False, server_default="2"),
    )
    op.create_index("ix_audit_timestamp", "audit_log", ["timestamp"])

    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(), primary_key=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("revoked_tokens")
    op.drop_index("ix_audit_timestamp", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_feedback_status", table_name="feedback_entries")
    op.drop_table("feedback_entries")
    op.drop_index("ix_letters_case", table_name="letters")
    op.drop_table("letters")
    op.drop_index("ix_cases_volunteer", table_name="cases")
    op.drop_index("ix_cases_session_status", table_name="cases")
    op.drop_table("cases")
    op.drop_table("residents")
    op.drop_table("sessions")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
