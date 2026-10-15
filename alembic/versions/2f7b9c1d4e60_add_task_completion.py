"""Track task completion separately from meeting-note approval."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "2f7b9c1d4e60"
down_revision = "b6e2a9407d13"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("action_items", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("action_items", sa.Column("completed_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_action_items_completed_by", "action_items", "registered_users",
                          ["completed_by_id"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("fk_action_items_completed_by", "action_items", type_="foreignkey")
    op.drop_column("action_items", "completed_by_id")
    op.drop_column("action_items", "completed_at")
