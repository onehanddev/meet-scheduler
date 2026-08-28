"""Create availability_windows table.

Revision ID: 20260828_05
Revises: 20260828_04
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_05"
down_revision: str | None = "20260828_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "availability_windows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host_id", sa.Uuid(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_availability_windows_host_id", "availability_windows", ["host_id"]
    )
    op.create_index(
        "ix_availability_windows_host_weekday",
        "availability_windows",
        ["host_id", "weekday"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_availability_windows_host_weekday", table_name="availability_windows"
    )
    op.drop_index("ix_availability_windows_host_id", table_name="availability_windows")
    op.drop_table("availability_windows")
