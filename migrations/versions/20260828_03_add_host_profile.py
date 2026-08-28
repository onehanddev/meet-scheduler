"""Add host profile fields.

Revision ID: 20260828_03
Revises: 20260828_02
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_03"
down_revision: str | None = "20260828_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("username", sa.String(length=30), nullable=True))
    op.add_column(
        "hosts", sa.Column("display_name", sa.String(length=100), nullable=True)
    )
    op.add_column("hosts", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_hosts_username_lower "
            "ON hosts (lower(username)) WHERE username IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_hosts_username_lower"))
    op.drop_column("hosts", "timezone")
    op.drop_column("hosts", "display_name")
    op.drop_column("hosts", "username")
