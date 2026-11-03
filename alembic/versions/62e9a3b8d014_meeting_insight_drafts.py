"""Independent analysis drafts; coordinate migration release."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision = "62e9a3b8d014"
down_revision = "92d6a10f4e72"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("meeting_insight_drafts",
        sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("transcript_hash", sa.String(64), nullable=False), sa.Column("payload", JSONB(), nullable=False),
        sa.Column("reviewed_by", sa.String(255)))
def downgrade():
    op.drop_table("meeting_insight_drafts")
