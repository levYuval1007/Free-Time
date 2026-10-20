"""Checks an itinerary proposed by the agent. The model only chooses places, their order and how long to stay;
every time in the result is computed here from real driving times, so the model cannot invent a schedule."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import hours
import planner

MIN_VISIT_MINUTES = 20
MAX_VISIT_MINUTES = 180
# Extra driving a stop may add compared with going straight to the destination: about 10 minutes out of the
# way and 10 minutes back to the road.
MAX_DETOUR_MINUTES = 20
# A plan this many minutes too late is fixed by shortening visits instead of being rejected.
MAX_AUTO_TRIM_MINUTES = 15


@dataclass
class TripContext:
    now: datetime
    arrive_by: datetime
    buffer_minutes: int
    origin: tuple  # (lon, lat)
    destination: tuple  # (lon, lat)
    # Places returned by searches during this run, by id. The agent may only pick from these.
    known_places: dict = field(default_factory=dict)
    # The direct driving route as (lon, lat) points, used to find places along the way.
    route: list = field(default_factory=list)

    @property
    def latest_arrival(self):
        return self.arrive_by - timedelta(minutes=self.buffer_minutes)


def _hours_that_day(place, moment):
    """The place's opening hours for the day of the visit, as text (empty when unknown)."""
    text = place.get("weekday_text")
    if not text or len(text) != 7:
        return ""
    local = moment + timedelta(minutes=place.get("utc_offset_minutes") or 0)
    return text[local.weekday()]  # Google lists Monday first, like Python


def _local_clock(moment, place):
    local = moment + timedelta(minutes=place.get("utc_offset_minutes") or 0)
    return local.strftime("%H:%M")


def _parse(proposed):
    """Turn the raw model output into [(place_id, visit_minutes | None)], plus any shape errors."""
    if not isinstance(proposed, list) or not proposed:
        return [], ["stops must be a non-empty list"]
    if len(proposed) > planner.MAX_STOPS:
        return [], [f"at most {planner.MAX_STOPS} stops are allowed, got {len(proposed)}"]
    parsed, errors, seen = [], [], set()
    for position, item in enumerate(proposed, start=1):
        place_id = item.get("place_id") if isinstance(item, dict) else None
        if not isinstance(place_id, str):
            errors.append(f"stop {position} has no place_id")
            continue
        if place_id in seen:
            errors.append(f"stop {position} repeats place_id {place_id}")
        seen.add(place_id)
        visit = item.get("visit_minutes")
        if visit is not None and (isinstance(visit, bool) or not isinstance(visit, (int, float))):
            errors.append(f"stop {position} visit_minutes must be a number")
            visit = None
        parsed.append((place_id, None if visit is None else int(visit)))
    return parsed, errors


def _detour_problems(places, grid, last, direct):
    """Stops that add too much driving compared with going straight to the destination."""
    problems = []
    if direct is None:
        return problems
    for index, (place, _) in enumerate(places, start=1):
        if grid[0][index] is None or grid[index][last] is None:
            continue
        detour = grid[0][index] + grid[index][last] - direct
        if detour > MAX_DETOUR_MINUTES:
            problems.append(
                f"'{place['name']}' adds about {round(detour)} minutes of driving compared with going "
                f"straight to the destination; the limit is {MAX_DETOUR_MINUTES}"
            )
    return problems


def _schedule(ctx, places, grid, last):
    """Times for visiting the places in order: (stops, problems, arrival, final_drive_minutes).

    stops is None when a leg has no route. problems lists places that are closed or have unknown hours.
    """
    problems = []
    clock = ctx.now
    stops = []
    for index, (place, visit) in enumerate(places, start=1):
        drive = grid[index - 1][index]
        if drive is None:
            return None, [f"there is no driving route to '{place['name']}'"], None, None
        arrive = clock + timedelta(minutes=drive)
        leave = arrive + timedelta(minutes=visit)
        window_end = leave + timedelta(minutes=planner.CLOSING_MARGIN_MINUTES)
        open_now = hours.is_open_during(place.get("periods"), place.get("utc_offset_minutes"), arrive, window_end)
        if open_now is None:
            problems.append(f"the opening hours of '{place['name']}' are unknown")
        elif not open_now:
            hours_text = _hours_that_day(place, arrive)
            problems.append(
                f"'{place['name']}' is not open for the whole visit "
                f"({_local_clock(arrive, place)}-{_local_clock(leave, place)} local time, "
                f"and it must stay open {planner.CLOSING_MARGIN_MINUTES} minutes after you leave)"
                + (f"; its hours that day: {hours_text}" if hours_text else "")
            )
        stops.append(
            {"place": place, "drive_minutes": drive, "arrive": arrive, "leave": leave, "visit_minutes": visit}
        )
        clock = leave
    final_drive = grid[last - 1][last]
    if final_drive is None:
        return None, ["there is no driving route from the last stop to the destination"], None, None
    return stops, problems, clock + timedelta(minutes=final_drive), final_drive


def _shorten(places, minutes):
    """The places with `minutes` taken off their visits, starting with the last stop and never below the
    minimum visit. None when the visits cannot give up that much."""
    shortened = list(places)
    for index in range(len(shortened) - 1, -1, -1):
        if minutes <= 0:
            break
        place, visit = shortened[index]
        cut = min(minutes, visit - MIN_VISIT_MINUTES)
        if cut > 0:
            shortened[index] = (place, visit - cut)
            minutes -= cut
    return shortened if minutes <= 0 else None


def validate_itinerary(ctx: TripContext, proposed, travel_matrix):
    """Returns (result, errors). result is None unless errors is empty.

    result has the same shape as planner.plan_stops: stops with place, drive_minutes, arrive, leave and
    visit_minutes, plus final_drive_minutes and arrive_destination.
    travel_matrix(points) gives driving minutes between points as a square matrix (None if unroutable).
    """
    parsed, errors = _parse(proposed)
    places = []
    for place_id, visit in parsed:
        place = ctx.known_places.get(place_id)
        if place is None:
            errors.append(f"place_id {place_id} was not returned by search_places in this run")
            continue
        if visit is not None and not MIN_VISIT_MINUTES <= visit <= MAX_VISIT_MINUTES:
            errors.append(
                f"'{place['name']}': visit_minutes must be between {MIN_VISIT_MINUTES} and {MAX_VISIT_MINUTES}"
            )
            continue
        places.append((place, visit if visit is not None else planner.visit_minutes(place)))
    if errors:
        return None, errors

    points = [ctx.origin, *[(place["lon"], place["lat"]) for place, _ in places], ctx.destination]
    grid = travel_matrix(points)
    last = len(points) - 1

    direct = grid[0][last]
    errors = _detour_problems(places, grid, last, direct)
    stops, problems, arrival, final_drive = _schedule(ctx, places, grid, last)
    errors += problems
    if stops is None:
        return None, errors

    trimmed = []
    if not errors and arrival > ctx.latest_arrival:
        late = math.ceil((arrival - ctx.latest_arrival).total_seconds() / 60)
        shortened = _shorten(places, late) if late <= MAX_AUTO_TRIM_MINUTES else None
        if shortened is not None:
            new_stops, new_problems, new_arrival, new_final = _schedule(ctx, shortened, grid, last)
            if not new_problems and new_arrival <= ctx.latest_arrival:
                trimmed = [
                    (before[0]["name"], before[1], after[1])
                    for before, after in zip(places, shortened)
                    if before[1] != after[1]
                ]
                stops, arrival, final_drive = new_stops, new_arrival, new_final
    if not errors and arrival > ctx.latest_arrival:
        late = round((arrival - ctx.latest_arrival).total_seconds() / 60)
        errors.append(
            f"you would reach the destination {late} minute{'' if late == 1 else 's'} after the latest allowed time "
            f"(the deadline minus a {ctx.buffer_minutes} minute safety margin); shorten a visit or drop a stop"
        )
    if errors:
        return None, errors
    result = {"stops": stops, "final_drive_minutes": final_drive, "arrive_destination": arrival}
    if trimmed:
        result["trimmed"] = trimmed
    return result, []
