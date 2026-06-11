"""Add letters.generation_meta for generation provenance (V-C2).

Revision ID: 20260611_01
Revises: 20260610_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260611_01"
down_revision = "20260610_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("letters", sa.Column("generation_meta", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("letters", "generation_meta")
