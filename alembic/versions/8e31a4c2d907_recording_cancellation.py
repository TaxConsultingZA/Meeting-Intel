"""Add cooperative job cancellation without changing active job uniqueness."""
from alembic import op
import sqlalchemy as sa

revision = "8e31a4c2d907"
down_revision = "7b2d9e4c6a10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recording_jobs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TYPE processingstate ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade():
    # PostgreSQL cannot remove an enum label safely while user rows may use it.
    op.drop_column("recording_jobs", "cancel_requested_at")
