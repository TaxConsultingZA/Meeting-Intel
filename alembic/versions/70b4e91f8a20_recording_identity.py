"""Separate recording identity from preserved processing/review history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "70b4e91f8a20"
down_revision = "40c8e12a9b71"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processed_items", sa.Column("identity_json", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("processed_items", "identity_json")
