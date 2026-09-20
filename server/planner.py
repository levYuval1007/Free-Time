import math
from datetime import datetime, timedelta

import hours

MAX_STOPS = 3
MAX_CANDIDATES = 40
MIN_RATING = 4.0
MIN_RATING_COUNT = 100
CLOSING_MARGIN_MINUTES = 15
DEFAULT_VISIT_MINUTES = 45
EXCLUDED_TYPES = {"bar", "beer_garden", "night_club", "casino", "liquor_store"}
VISIT_MINUTES = {
    "museum": 90,
    "art_museum": 90,
    "art_gallery": 60,
    "botanical_garden": 60,
    "park": 45,
    "tourist_attraction": 45,
    "historical_landmark": 30,
}

# Rows and columns of the travel matrix follow this order: origin, destination, then the candidates.
ORIGIN = 0
DESTINATION = 1
FIRST_CANDIDATE = 2


def visit_minutes(place):
    for place_type in [place.get("primary_type"), *place.get("types", [])]:
        if place_type in VISIT_MINUTES:
            return VISIT_MINUTES[place_type]
    return DEFAULT_VISIT_MINUTES


def quality(place):
    return (place["rating"] - 3.5) * math.log10(1 + place["rating_count"])


def is_candidate(place):
    if place.get("business_status") not in (None, "OPERATIONAL"):
        return False
    if not place.get("periods") or place.get("utc_offset_minutes") is None:
        return False
    rating = place.get("rating")
    if rating is None or rating < MIN_RATING or (place.get("rating_count") or 0) < MIN_RATING_COUNT:
        return False
    return not EXCLUDED_TYPES & set(place.get("types", []))


def select_candidates(places):
    unique = {}
    for place in places:
        unique.setdefault(place["id"], place)
    good = [place for place in unique.values() if is_candidate(place)]
    good.sort(key=lambda place: (-quality(place), place["id"]))
    return good[:MAX_CANDIDATES]


def plan_stops(candidates, matrix, now: datetime, arrive_by: datetime, buffer_minutes: int):
    """Pick up to MAX_STOPS candidates that fit between now and the deadline.

    matrix[i][j] is the driving time in minutes from node i to node j (None when unroutable).
    Returns None when no stop fits.
    """
    limit = arrive_by - timedelta(minutes=buffer_minutes)
    best = None

    def search(clock, position, chosen, total_quality, total_drive):
        nonlocal best
        if chosen:
            back = matrix[position][DESTINATION]
            if back is not None:
                arrival = clock + timedelta(minutes=back)
                if arrival <= limit:
                    key = (round(total_quality, 6), -(total_drive + back))
                    if best is None or key > best[0]:
                        best = (key, list(chosen), arrival, back)
        if len(chosen) == MAX_STOPS:
            return
        used = {stop["index"] for stop in chosen}
        for index, place in enumerate(candidates):
            if index in used:
                continue
            node = FIRST_CANDIDATE + index
            drive = matrix[position][node]
            back = matrix[node][DESTINATION]
            if drive is None or back is None:
                continue
            arrive = clock + timedelta(minutes=drive)
            leave = arrive + timedelta(minutes=visit_minutes(place))
            if leave + timedelta(minutes=back) > limit:
                continue
            window_end = leave + timedelta(minutes=CLOSING_MARGIN_MINUTES)
            if not hours.is_open_during(place.get("periods"), place.get("utc_offset_minutes"), arrive, window_end):
                continue
            chosen.append({"index": index, "arrive": arrive, "leave": leave, "drive": drive})
            search(leave, node, chosen, total_quality + quality(place), total_drive + drive)
            chosen.pop()

    search(now, ORIGIN, [], 0.0, 0.0)
    if best is None:
        return None
    _, chosen, arrival, final_drive = best
    return {
        "stops": [
            {
                "place": candidates[stop["index"]],
                "drive_minutes": stop["drive"],
                "arrive": stop["arrive"],
                "leave": stop["leave"],
                "visit_minutes": visit_minutes(candidates[stop["index"]]),
            }
            for stop in chosen
        ],
        "final_drive_minutes": final_drive,
        "arrive_destination": arrival,
    }
