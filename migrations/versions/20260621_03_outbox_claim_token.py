"""v9 Important #1: outbox claim_token for ownership-checked acknowledgement

Revision ID: 20260621_03
Revises: 20260621_02
"""
import sqlalchemy as sa
from alembic import op

revision = "20260621_03"
down_revision = "20260621_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_checkpoint_outbox",
                  sa.Column("claim_token", sa.String(), nullable=True))


def downgrade():
    op.drop_column("audit_checkpoint_outbox", "claim_token")
