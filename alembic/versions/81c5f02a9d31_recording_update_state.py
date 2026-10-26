"""Persist per-user incremental recording update results and Graph cursors."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "81c5f02a9d31"
down_revision = "70b4e91f8a20"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("user_sync_states", sa.Column("details_json", postgresql.JSONB(), nullable=True))

def downgrade():
    op.drop_column("user_sync_states", "details_json")
