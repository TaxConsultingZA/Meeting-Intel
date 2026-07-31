"""bind immutable Entra identity

Revision ID: a142cc78536e
Revises: 9d331bf017aa
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a142cc78536e"
down_revision: Union[str, None] = "9d331bf017aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "registered_users",
        sa.Column("entra_oid", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_registered_users_entra_oid"),
        "registered_users",
        ["entra_oid"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_registered_users_entra_oid"),
        table_name="registered_users",
    )
    op.drop_column("registered_users", "entra_oid")
