import math
from datetime import datetime

MIN_BUFFER_MINUTES = 15
BUFFER_FRACTION = 0.10
MIN_FREE_MINUTES = 45


def compute_free_time(minutes_until_arrival, drive_minutes):
    buffer = max(MIN_BUFFER_MINUTES, math.ceil(drive_minutes * BUFFER_FRACTION))
    free = minutes_until_arrival - drive_minutes - buffer
    if minutes_until_arrival < drive_minutes:
        status = "impossible"
    elif free < MIN_FREE_MINUTES:
        status = "go_direct"
    else:
        status = "ok"
    return {
        "status": status,
        "drive_minutes": drive_minutes,
        "buffer_minutes": buffer,
        "free_minutes": max(free, 0),
    }


def plan_budget(arrive_by, now, drive_minutes):
    if arrive_by.tzinfo is None or now.tzinfo is None:
        raise ValueError("arrive_by and now must be timezone-aware")
    minutes_until = math.floor((arrive_by - now).total_seconds() / 60)
    return compute_free_time(minutes_until, drive_minutes)


def parse_arrive_by(text):
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("arrive_by must include a timezone offset")
    return parsed
