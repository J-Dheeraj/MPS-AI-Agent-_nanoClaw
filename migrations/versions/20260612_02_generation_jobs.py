"""add generation_jobs table for idempotency and restart recovery

Revision ID: 20260612_02
Revises: 20260612_01
Create Date: 2026-06-12

V-H8: Tracks letter generation requests for idempotency (duplicate requests
are detected via idempotency_key) and restart recovery (running jobs are
reset to pending on startup).
"""

from alembic import op
import sqlalchemy as sa

revision = "20260612_02"
down_revision = "20260612_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("letter_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["letter_id"], ["letters.id"]),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_generation_jobs_letter_id", "generation_jobs", ["letter_id"])


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_letter_id", "generation_jobs")
    op.drop_table("generation_jobs")
