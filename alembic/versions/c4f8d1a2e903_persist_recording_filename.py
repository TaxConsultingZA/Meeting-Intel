"""Persist the OneDrive filename for discovered recordings."""
from alembic import op
import sqlalchemy as sa

revision = "c4f8d1a2e903"
down_revision = "ae52c790b316"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processed_items", sa.Column("filename", sa.String(512), nullable=True))


def downgrade():
    op.drop_column("processed_items", "filename")
