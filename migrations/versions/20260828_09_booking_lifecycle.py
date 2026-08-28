"""Booking lifecycle: predecessor history for reschedule.

Revision ID: 20260828_09
Revises: 20260828_08
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_09"
down_revision: str | None = "20260828_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("predecessor_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_predecessor_id",
        "bookings",
        "bookings",
        ["predecessor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_bookings_predecessor_id", "bookings", ["predecessor_id"])


def downgrade() -> None:
    op.drop_index("ix_bookings_predecessor_id", table_name="bookings")
    op.drop_constraint(
        "fk_bookings_predecessor_id", "bookings", type_="foreignkey"
    )
    op.drop_column("bookings", "predecessor_id")
