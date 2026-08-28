import re
from datetime import time

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_time(value: str) -> time:
    m = TIME_RE.match(value.strip())
    if not m:
        raise ValueError("time must be HH:MM 00:00-23:59")
    return time(hour=int(m.group(1)), minute=int(m.group(2)))


def validate_windows_no_overlap(windows: list[dict]) -> None:
    """Raise ValueError if any same-weekday windows overlap.

    Adjacent windows are allowed (end == start).
    Expects windows with weekday, start_time, end_time where start_time < end_time.
    """
    by_weekday: dict[int, list[tuple[time, time]]] = {}
    for w in windows:
        wd = w["weekday"]
        by_weekday.setdefault(wd, []).append((w["start_time"], w["end_time"]))
    for wd, intervals in by_weekday.items():
        intervals.sort(key=lambda x: x[0])
        for i in range(1, len(intervals)):
            prev_start, prev_end = intervals[i - 1]
            cur_start, cur_end = intervals[i]
            if cur_start < prev_end:
                msg = (
                    f"overlapping windows on weekday {wd}: "
                    f"{prev_start}-{prev_end} overlaps {cur_start}-{cur_end}"
                )
                raise ValueError(msg)
