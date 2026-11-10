"""Track selectable Business Units and protect assignments from stale writes."""

import sqlalchemy as sa
from alembic import op

revision = "74f63b81ac20"
down_revision = "68c4a7fe210d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("business_units", sa.Column(
        "is_selectable", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("registered_users", sa.Column(
        "business_unit_version", sa.Integer(), nullable=False, server_default="0",
    ))
    op.execute("""
        UPDATE business_units SET is_selectable = true
        WHERE name IN (
            'Africorp', 'AI Department', 'BAM', 'CPD Consortium', 'Crypto Tax consulting',
            'DEV', 'FBPS', 'FE', 'IT', 'Marketing', 'MySarsAssistant', 'Rem',
            'SubmitMyVisa', 'TRS', 'Xpatweb'
        )
    """)


def downgrade():
    op.drop_column("registered_users", "business_unit_version")
    op.drop_column("business_units", "is_selectable")
