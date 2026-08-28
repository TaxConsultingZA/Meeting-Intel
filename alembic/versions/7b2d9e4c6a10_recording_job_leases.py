"""Fence worker leases and prevent concurrent active jobs for one recording.

Revision ID: 7b2d9e4c6a10
Revises: 3f7a2b61c9d4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "7b2d9e4c6a10"
down_revision = "3f7a2b61c9d4"
branch_labels = None
depends_on = None


def upgrade():
    # Fail safely on legacy duplicates; never silently delete user jobs.
    duplicate = op.get_bind().execute(sa.text("""
        SELECT drive_item_id FROM recording_jobs
        WHERE status IN ('pending', 'processing')
        GROUP BY drive_item_id HAVING count(*) > 1 LIMIT 1
    """)).first()
    if duplicate:
        raise RuntimeError("Resolve duplicate active recording jobs before migrating")
    op.add_column("recording_jobs", sa.Column("lease_token", postgresql.UUID(as_uuid=True)))
    op.create_index(
        "uq_recording_jobs_active_item", "recording_jobs", ["drive_item_id"],
        unique=True, postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade():
    op.drop_index("uq_recording_jobs_active_item", table_name="recording_jobs")
    op.drop_column("recording_jobs", "lease_token")
