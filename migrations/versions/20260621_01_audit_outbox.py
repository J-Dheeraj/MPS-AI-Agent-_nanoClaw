"""v6 Important #1: durable audit checkpoint outbox

Revision ID: 20260621_01
Revises: 20260620_01
"""
import sqlalchemy as sa
from alembic import op

revision = "20260621_01"
down_revision = "20260620_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_checkpoint_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("line", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_audit_outbox_undelivered",
        "audit_checkpoint_outbox",
        ["delivered_at", "created_at"],
    )


def downgrade():
    op.drop_index("ix_audit_outbox_undelivered", "audit_checkpoint_outbox")
    op.drop_table("audit_checkpoint_outbox")
