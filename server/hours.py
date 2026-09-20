import math
from datetime import datetime, timedelta

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


def _week_minute(point):
    return point["day"] * MINUTES_PER_DAY + point.get("hour", 0) * 60 + point.get("minute", 0)


def _open_intervals(periods):
    """Merged opening intervals in minutes from Sunday 00:00, repeated one week either side.

    Returns None when the place is open all the time (a single open point with no close, per Google).
    """
    raw = []
    for period in periods:
        opening = period.get("open")
        if opening is None:
            continue
        closing = period.get("close")
        if closing is None:
            return None
        start = _week_minute(opening)
        end = _week_minute(closing)
        if end <= start:
            end += MINUTES_PER_WEEK
        raw.append((start, end))

    spread = sorted(
        (start + shift, end + shift)
        for start, end in raw
        for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK)
    )
    merged = []
    for start, end in spread:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def is_open_during(periods, utc_offset_minutes, start_utc: datetime, end_utc: datetime):
    """True/False when the whole visit fits inside opening hours; None when the hours are unknown."""
    if not periods or utc_offset_minutes is None:
        return None
    intervals = _open_intervals(periods)
    if intervals is None:
        return True

    local_start = (start_utc + timedelta(minutes=utc_offset_minutes)).replace(second=0, microsecond=0)
    duration = max(0, math.ceil((end_utc - start_utc).total_seconds() / 60))
    day = (local_start.weekday() + 1) % 7  # Google counts Sunday as 0, Python counts Monday as 0
    start = day * MINUTES_PER_DAY + local_start.hour * 60 + local_start.minute
    end = start + duration
    return any(open_at <= start and end <= close_at for open_at, close_at in intervals)
