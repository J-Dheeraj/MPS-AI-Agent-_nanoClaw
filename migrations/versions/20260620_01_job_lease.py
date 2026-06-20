"""C3: generation job lease + retry columns

Revision ID: 20260620_01
Revises: 20260612_02
"""
import sqlalchemy as sa
from alembic import op

revision = "20260620_01"
down_revision = "20260612_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_jobs",
                  sa.Column("retry_count", sa.Integer(), nullable=False,
                            server_default="0"))
    op.add_column("generation_jobs",
                  sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("generation_jobs",
                  sa.Column("last_error", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("generation_jobs", "last_error")
    op.drop_column("generation_jobs", "lease_expires_at")
    op.drop_column("generation_jobs", "retry_count")
