from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from meet_scheduler.database import Base


class MeetingType(Base):
    __tablename__ = "meeting_types"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    host_id: Mapped[UUID] = mapped_column(
        ForeignKey("hosts.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    event_slug: Mapped[str] = mapped_column(String(30), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    minimum_notice: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    __table_args__ = (
        Index(
            "uq_meeting_types_host_slug_lower",
            host_id,
            func.lower(event_slug),
            unique=True,
        ),
    )
