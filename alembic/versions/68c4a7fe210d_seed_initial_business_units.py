"""Seed the initial Business Unit catalog while retaining historical assignments."""

from alembic import op

revision = "68c4a7fe210d"
down_revision = "62e9a3b8d014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO business_units (name) VALUES
            ('Africorp'),
            ('AI Department'),
            ('BAM'),
            ('CPD Consortium'),
            ('Crypto Tax consulting'),
            ('DEV'),
            ('FBPS'),
            ('FE'),
            ('IT'),
            ('Marketing'),
            ('MySarsAssistant'),
            ('Rem'),
            ('SubmitMyVisa'),
            ('TRS'),
            ('Xpatweb')
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade():
    # A seeded row may already have existed or may now have users assigned to it.
    pass
