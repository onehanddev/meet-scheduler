"""Create bookings table.

Revision ID: 20260828_06
Revises: 20260828_05
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_06"
down_revision: str | None = "20260828_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_type_id", sa.Uuid(), nullable=False),
        sa.Column("invitee_name", sa.String(length=200), nullable=False),
        sa.Column("invitee_email", sa.String(length=320), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'confirmed'"),
        ),
        sa.Column("management_token_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["meeting_type_id"], ["meeting_types.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_host_id", "bookings", ["host_id"])
    op.create_index("ix_bookings_host_start", "bookings", ["host_id", "start_time"])
    op.create_index("ix_bookings_host_status", "bookings", ["host_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_bookings_host_status", table_name="bookings")
    op.drop_index("ix_bookings_host_start", table_name="bookings")
    op.drop_index("ix_bookings_host_id", table_name="bookings")
    op.drop_table("bookings")
