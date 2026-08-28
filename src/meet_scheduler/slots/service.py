"""Slot generation — time-correct, provider-isolated."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session


def get_now() -> datetime:
    """Request-scoped clock. Patchable in tests via unittest.mock.patch."""
    return datetime.now(UTC)


def _host_local_to_utc(  # noqa: E501
    slot_date: date, start: time, host_tz: ZoneInfo
) -> datetime | None:
    """Convert host wall time to UTC, returning None for DST gap (nonexistent)."""
    naive = datetime.combine(slot_date, start)
    local = naive.replace(tzinfo=host_tz)
    utc = local.astimezone(UTC)
    back = utc.astimezone(host_tz)
    if (back.year, back.month, back.day, back.hour, back.minute) != (
        naive.year,
        naive.month,
        naive.day,
        naive.hour,
        naive.minute,
    ):
        return None
    return utc


def generate_slots(
    *,
    windows: list[dict],
    host_timezone: str,
    duration: int,
    from_date: date,
    to_date: date,
    invitee_timezone: str,
    now: datetime,
    minimum_notice: int,
    horizon_days: int,
    confirmed_bookings: list[tuple[datetime, datetime]] | None = None,
) -> list[dict]:
    """Pure slot calculation consumed via provider boundary.

    `windows` are dicts {weekday, start_time: time, end_time: time} in host local.
    `confirmed_bookings` are list of (start_utc, end_utc) for host.
    Returns list of {start, end} as invitee-local ISO strings plus UTC.
    """
    host_tz = ZoneInfo(host_timezone)
    invitee_tz = ZoneInfo(invitee_timezone)
    notice_cutoff = now.astimezone(UTC) + timedelta(minutes=minimum_notice)
    horizon_cutoff = now.astimezone(UTC) + timedelta(days=horizon_days)
    confirmed_bookings = confirmed_bookings or []

    # Group windows by weekday
    by_wd: dict[int, list[tuple[time, time]]] = {}
    for w in windows:
        wd = int(w["weekday"])
        st = w["start_time"]
        en = w["end_time"]
        # normalize to time objects if strings
        if isinstance(st, str):
            h, m = map(int, st.split(":"))
            st = time(hour=h, minute=m)
        if isinstance(en, str):
            h, m = map(int, en.split(":"))
            en = time(hour=h, minute=m)
        by_wd.setdefault(wd, []).append((st, en))

    result: list[dict] = []
    seen_utc: set[datetime] = set()

    cur_date = from_date
    one_day = timedelta(days=1)
    while cur_date <= to_date:
        wd = cur_date.weekday()  # Monday 0 .. Sunday 6
        for win_start, win_end in sorted(by_wd.get(wd, [])):
            win_start_min = win_start.hour * 60 + win_start.minute
            win_end_min = win_end.hour * 60 + win_end.minute
            # advance in duration steps
            cur_min = win_start_min
            while cur_min + duration <= win_end_min:
                cur_hour, cur_mm = divmod(cur_min, 60)
                cur_t = time(hour=cur_hour, minute=cur_mm)
                slot_start_utc = _host_local_to_utc(cur_date, cur_t, host_tz)
                if slot_start_utc is None:
                    cur_min += duration
                    continue
                slot_end_utc = slot_start_utc + timedelta(minutes=duration)
                # horizon / notice
                if slot_start_utc < notice_cutoff:
                    cur_min += duration
                    continue
                if slot_start_utc > horizon_cutoff:
                    cur_min += duration
                    continue
                # overlap: slot_start < booking_end and booking_start < slot_end
                overlap = False
                for b_start, b_end in confirmed_bookings:
                    if slot_start_utc < b_end and b_start < slot_end_utc:
                        overlap = True
                        break
                if overlap:
                    cur_min += duration
                    continue
                # DST ambiguous duplicate prevention
                if slot_start_utc in seen_utc:
                    cur_min += duration
                    continue
                seen_utc.add(slot_start_utc)
                # Convert to invitee tz for response
                invitee_start = slot_start_utc.astimezone(invitee_tz)
                invitee_end = slot_end_utc.astimezone(invitee_tz)
                result.append(
                    {
                        "start": invitee_start.isoformat(),
                        "end": invitee_end.isoformat(),
                        "start_utc": slot_start_utc.isoformat(),
                        "end_utc": slot_end_utc.isoformat(),
                    }
                )
                cur_min += duration
        cur_date = cur_date + one_day

    result.sort(key=lambda s: s["start_utc"])
    return result


def fetch_confirmed_bookings(
    session: Session, host_id
) -> list[tuple[datetime, datetime]]:
    """Load confirmed bookings for host; tolerant if table missing."""
    try:
        from meet_scheduler.bookings.models import Booking

        rows = (
            session.query(Booking)
            .filter(Booking.host_id == host_id, Booking.status == "confirmed")
            .all()
        )
        return [(r.start_time, r.end_time) for r in rows]
    except Exception:
        return []
