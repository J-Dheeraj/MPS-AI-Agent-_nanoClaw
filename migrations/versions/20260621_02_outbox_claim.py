"""v8 Important #1: outbox claimed_at for leased delivery (no lock held during HTTP)

Revision ID: 20260621_02
Revises: 20260621_01
"""
import sqlalchemy as sa
from alembic import op

revision = "20260621_02"
down_revision = "20260621_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_checkpoint_outbox",
                  sa.Column("claimed_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("audit_checkpoint_outbox", "claimed_at")
