"""Store manual meeting decisions without changing legacy meeting data."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "51d8f2a7c903"
down_revision = "81c5f02a9d31"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("meeting_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False))
    op.create_index("ix_meeting_decisions_meeting_id", "meeting_decisions", ["meeting_id"])


def downgrade():
    op.drop_index("ix_meeting_decisions_meeting_id", table_name="meeting_decisions")
    op.drop_table("meeting_decisions")
