"""Default timezone Asia/Kolkata for hosts.

Revision ID: 20260828_08
Revises: 20260828_07
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_08"
down_revision: str | None = "20260828_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE hosts SET timezone = 'Asia/Kolkata' WHERE timezone IS NULL")
    )
    op.alter_column("hosts", "timezone", server_default="Asia/Kolkata")


def downgrade() -> None:
    op.alter_column("hosts", "timezone", server_default=None)
