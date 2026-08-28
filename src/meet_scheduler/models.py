"""Re-export domain models for backward compat (alembic, tests).

Canonical locations are now vertical slices:
  hosts -> meet_scheduler.hosts.models
  meeting_types -> meet_scheduler.meeting_types.models
"""

from meet_scheduler.availability.models import AvailabilityWindow
from meet_scheduler.bookings.models import Booking
from meet_scheduler.hosts.models import Host, RefreshToken
from meet_scheduler.meeting_types.models import MeetingType

__all__ = ["AvailabilityWindow", "Booking", "Host", "MeetingType", "RefreshToken"]
