from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from meet_scheduler.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    host_id: Mapped[UUID] = mapped_column(
        ForeignKey("hosts.id", ondelete="CASCADE"), nullable=False
    )
    meeting_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("meeting_types.id", ondelete="CASCADE"), nullable=False
    )
    invitee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    invitee_email: Mapped[str] = mapped_column(String(320), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed")
    management_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    predecessor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ExcludeConstraint(
            (host_id, "="),
            (func.tstzrange(start_time, end_time, "[)"), "&&"),
            name="ex_bookings_host_confirmed_overlap",
            using="gist",
            where=text("status = 'confirmed'"),
        ),
        Index("ix_bookings_host_id", "host_id"),
        Index("ix_bookings_host_start", "host_id", "start_time"),
        Index("ix_bookings_host_status", "host_id", "status"),
    )
