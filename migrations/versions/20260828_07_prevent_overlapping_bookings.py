"""Prevent overlapping confirmed bookings.

Revision ID: 20260828_07
Revises: 20260828_06
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_07"
down_revision: str | None = "20260828_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE bookings
        ADD CONSTRAINT ex_bookings_host_confirmed_overlap
        EXCLUDE USING gist (
            host_id WITH =,
            tstzrange(start_time, end_time, '[)') WITH &&
        )
        WHERE (status = 'confirmed')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE bookings
        DROP CONSTRAINT ex_bookings_host_confirmed_overlap
        """
    )
