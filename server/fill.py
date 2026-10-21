"""Uses up spare time: when a plan would leave much more than the wanted slack at the destination, the visits are
lengthened (within sensible limits) so that the traveller arrives not too long before the deadline.

It only changes how long each stop lasts. Driving times stay as they are, so no routing request is needed, and the
opening hours of every stop are checked again for the new times.
"""

import math
from datetime import timedelta

import hours
import planner
import validator

MAX_SLACK_MINUTES = 40  # more spare time than this at arrival is filled with longer visits
TARGET_SLACK_MINUTES = 30  # where the extension stops (never below the safety margin)
STEP_MINUTES = 5
MAX_VISIT_FACTOR = 1.5  # a visit may grow to this many times the typical visit for that kind of place


def _slack_minutes(arrival, arrive_by):
    return (arrive_by - arrival).total_seconds() / 60


def _caps(stops):
    """The longest each visit may become: one and a half times the typical visit (in whole steps), at most the validator's maximum, and never less
    than what the plan already has."""
    return [
        max(
            stop["visit_minutes"],
            min(validator.MAX_VISIT_MINUTES, int(MAX_VISIT_FACTOR * planner.visit_minutes(stop["place"])) // STEP_MINUTES * STEP_MINUTES),
        )
        for stop in stops
    ]


def _schedule(stops, visits, now, final_drive, latest_arrival):
    """New times for the given visit lengths: (stops, arrival) or None if a stop would be closed or the plan late."""
    clock = now
    scheduled = []
    for stop, visit in zip(stops, visits):
        arrive = clock + timedelta(minutes=stop["drive_minutes"])
        leave = arrive + timedelta(minutes=visit)
        window_end = leave + timedelta(minutes=planner.CLOSING_MARGIN_MINUTES)
        place = stop["place"]
        if not hours.is_open_during(place.get("periods"), place.get("utc_offset_minutes"), arrive, window_end):
            return None
        scheduled.append({**stop, "arrive": arrive, "leave": leave, "visit_minutes": visit})
        clock = leave
    arrival = clock + timedelta(minutes=final_drive)
    if arrival > latest_arrival:
        return None
    return scheduled, arrival


def fill_free_time(chosen, now, arrive_by, buffer_minutes):
    """Returns (plan, extensions). The plan is a copy with longer visits when there was too much slack, otherwise the
    same plan; extensions lists (place name, visit before, visit after) for each stop that grew."""
    stops = chosen["stops"]
    if not stops:
        return chosen, []
    slack = _slack_minutes(chosen["arrive_destination"], arrive_by)
    if slack <= MAX_SLACK_MINUTES:
        return chosen, []

    want = max(TARGET_SLACK_MINUTES, buffer_minutes)
    remaining = math.floor(slack - want)
    if remaining <= 0:
        return chosen, []

    final_drive = chosen["final_drive_minutes"]
    latest_arrival = arrive_by - timedelta(minutes=buffer_minutes)
    visits = [stop["visit_minutes"] for stop in stops]
    caps = _caps(stops)
    locked = set()

    while remaining > 0 and len(locked) < len(stops):
        grew = False
        for index in range(len(stops)):
            if remaining <= 0:
                break
            if index in locked:
                continue
            amount = min(STEP_MINUTES, remaining, caps[index] - visits[index])
            if amount <= 0:
                locked.add(index)
                continue
            trial = list(visits)
            trial[index] += amount
            if _schedule(stops, trial, now, final_drive, latest_arrival) is None:
                locked.add(index)
                continue
            visits = trial
            remaining -= amount
            grew = True
        if not grew:
            break

    if visits == [stop["visit_minutes"] for stop in stops]:
        return chosen, []
    scheduled, arrival = _schedule(stops, visits, now, final_drive, latest_arrival)
    extensions = [
        (before["place"]["name"], before["visit_minutes"], after["visit_minutes"])
        for before, after in zip(stops, scheduled)
        if before["visit_minutes"] != after["visit_minutes"]
    ]
    return {**chosen, "stops": scheduled, "arrive_destination": arrival}, extensions
