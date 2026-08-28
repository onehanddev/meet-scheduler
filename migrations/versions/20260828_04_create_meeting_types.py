"""Create meeting_types table.

Revision ID: 20260828_04
Revises: 20260828_03
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_04"
down_revision: str | None = "20260828_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("event_slug", sa.String(length=30), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "minimum_notice", sa.Integer(), nullable=False, server_default=sa.text("60")
        ),
        sa.Column(
            "horizon_days", sa.Integer(), nullable=False, server_default=sa.text("60")
        ),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_id", name="uq_meeting_types_host_id"),
    )
    op.create_index(
        "uq_meeting_types_host_slug_lower",
        "meeting_types",
        [sa.text("host_id"), sa.text("lower(event_slug)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_meeting_types_host_slug_lower", table_name="meeting_types")
    op.drop_table("meeting_types")
