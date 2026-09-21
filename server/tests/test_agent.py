import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_tools
import places
import validator

NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)  # Sunday 12:00 in Israel (UTC+3)
ALWAYS_OPEN = [{"open": {"day": 0, "hour": 0, "minute": 0}}]
# Open Sunday 09:00-17:00 local time only.
SUNDAY_DAYTIME = [{"open": {"day": 0, "hour": 9, "minute": 0}, "close": {"day": 0, "hour": 17, "minute": 0}}]
ORIGIN = (34.78, 32.08)
DESTINATION = (35.21, 31.77)


def place(place_id, periods=ALWAYS_OPEN, rating=4.6, count=1000, lat=32.07, lon=34.79, types=("park",)):
    return {
        "id": place_id,
        "name": place_id.upper(),
        "lat": lat,
        "lon": lon,
        "types": list(types),
        "primary_type": types[0],
        "rating": rating,
        "rating_count": count,
        "business_status": "OPERATIONAL",
        "periods": periods,
        "weekday_text": ["Monday: 9-5"] * 7,
        "utc_offset_minutes": 180,
    }


def uniform_matrix(minutes):
    def matrix(points):
        return [[0 if i == j else minutes for j in range(len(points))] for i in range(len(points))]

    return matrix


def context(places_list, deadline_minutes=240, buffer=15):
    ctx = validator.TripContext(
        now=NOW,
        arrive_by=NOW + timedelta(minutes=deadline_minutes),
        buffer_minutes=buffer,
        origin=ORIGIN,
        destination=DESTINATION,
    )
    ctx.known_places = {p["id"]: p for p in places_list}
    return ctx


class ValidatorTests(unittest.TestCase):
    def check(self, ctx, stops, minutes=10):
        return validator.validate_itinerary(ctx, stops, uniform_matrix(minutes))

    def test_accepts_a_valid_plan_and_computes_the_schedule(self):
        ctx = context([place("a"), place("b")])
        result, errors = self.check(ctx, [{"place_id": "a", "visit_minutes": 30}, {"place_id": "b"}])
        self.assertEqual(errors, [])
        first, second = result["stops"]
        self.assertEqual(first["arrive"], NOW + timedelta(minutes=10))
        self.assertEqual(first["leave"], NOW + timedelta(minutes=40))
        self.assertEqual(second["arrive"], NOW + timedelta(minutes=50))
        self.assertEqual(second["visit_minutes"], 45)  # the default for a park
        self.assertEqual(result["arrive_destination"], second["leave"] + timedelta(minutes=10))

    def test_rejects_a_place_that_was_never_found(self):
        _, errors = self.check(context([place("a")]), [{"place_id": "invented"}])
        self.assertIn("not returned by search_places", errors[0])

    def test_rejects_duplicates_and_too_many_stops(self):
        ctx = context([place("a"), place("b"), place("c"), place("d")])
        self.assertTrue(self.check(ctx, [{"place_id": "a"}, {"place_id": "a"}])[1])
        self.assertIn("at most", self.check(ctx, [{"place_id": p} for p in "abcd"])[1][0])

    def test_rejects_empty_and_malformed_input(self):
        ctx = context([place("a")])
        self.assertTrue(self.check(ctx, [])[1])
        self.assertTrue(self.check(ctx, "a")[1])
        self.assertTrue(self.check(ctx, [{"name": "a"}])[1])
        self.assertTrue(self.check(ctx, ["a"])[1])

    def test_rejects_unreasonable_visit_lengths(self):
        ctx = context([place("a")])
        self.assertTrue(self.check(ctx, [{"place_id": "a", "visit_minutes": 5}])[1])
        self.assertTrue(self.check(ctx, [{"place_id": "a", "visit_minutes": 500}])[1])
        self.assertTrue(self.check(ctx, [{"place_id": "a", "visit_minutes": "long"}])[1])

    def test_rejects_a_place_that_is_closed_during_the_visit(self):
        closed_soon = place("a", periods=SUNDAY_DAYTIME)
        ctx = context([closed_soon])
        # Arrive 12:10 local, but a 5 hour visit runs past the 17:00 close.
        _, errors = self.check(ctx, [{"place_id": "a", "visit_minutes": 180}], minutes=10)
        self.assertEqual(errors, [])
        # Start late enough that the visit would end after closing time.
        late = validator.TripContext(
            now=NOW + timedelta(hours=4, minutes=30),
            arrive_by=NOW + timedelta(hours=9),
            buffer_minutes=15,
            origin=ORIGIN,
            destination=DESTINATION,
            known_places={"a": closed_soon},
        )
        _, errors = validator.validate_itinerary(late, [{"place_id": "a", "visit_minutes": 60}], uniform_matrix(10))
        self.assertIn("not open", errors[0])

    def test_rejects_unknown_opening_hours(self):
        _, errors = self.check(context([place("a", periods=None)]), [{"place_id": "a"}])
        self.assertIn("unknown", errors[0])

    def test_rejects_arriving_after_the_deadline_less_buffer(self):
        ctx = context([place("a")], deadline_minutes=70, buffer=15)
        # 10 + 45 + 10 = 65 minutes is later than the 55 allowed.
        _, errors = self.check(ctx, [{"place_id": "a"}])
        self.assertIn("after the latest allowed time", errors[0])
        ok, errors = self.check(ctx, [{"place_id": "a", "visit_minutes": 30}])
        self.assertEqual(errors, [])
        self.assertEqual(ok["arrive_destination"], NOW + timedelta(minutes=50))

    def test_rejects_unroutable_legs(self):
        def matrix(points):
            grid = [[5] * len(points) for _ in points]
            grid[0][1] = None
            return grid

        _, errors = validator.validate_itinerary(context([place("a")]), [{"place_id": "a"}], matrix)
        self.assertIn("no driving route", errors[0])


class FakeSearch:
    def __init__(self, found):
        self.found = found
        self.calls = []

    def __call__(self, lat, lon, radius, types=None):
        self.calls.append((lat, lon, radius, types))
        return self.found


def toolbox(found, deadline_minutes=240, minutes=10):
    ctx = context([], deadline_minutes)
    search = FakeSearch(found)
    return agent_tools.ToolBox(ctx, search, uniform_matrix(minutes)), search


class ToolBoxTests(unittest.TestCase):
    def test_search_returns_compact_candidates_and_remembers_them(self):
        box, search = toolbox([place("a"), place("b", rating=3.0)])
        text, is_error = box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        self.assertFalse(is_error)
        found = json.loads(text)
        self.assertEqual([p["id"] for p in found], ["a"])  # the low rated place is filtered out
        self.assertEqual(found[0]["hours_today"], "Monday: 9-5")
        self.assertEqual(list(box.ctx.known_places), ["a"])
        self.assertEqual(search.calls, [(32.08, 34.78, 2000, None)])

    def test_search_rejects_bad_arguments_without_calling_google(self):
        box, search = toolbox([place("a")])
        for args in (
            {"lat": "x", "lon": 34.78, "radius_m": 2000},
            {"lat": 32.08, "lon": 34.78, "radius_m": 100},
            {"lat": 32.08, "lon": 34.78, "radius_m": 99999},
            {"lat": 32.08, "lon": 34.78, "radius_m": 2000, "types": ["night_club"]},
            {"lat": 10.0, "lon": 10.0, "radius_m": 2000},  # far from the trip
        ):
            _, is_error = box.run("search_places", args)
            self.assertTrue(is_error, args)
        self.assertEqual(search.calls, [])

    def test_search_limit(self):
        box, _ = toolbox([place("a")])
        args = {"lat": 32.08, "lon": 34.78, "radius_m": 2000}
        for _ in range(agent_tools.MAX_SEARCHES):
            self.assertFalse(box.run("search_places", args)[1])
        self.assertTrue(box.run("search_places", args)[1])

    def test_places_failure_becomes_a_tool_error(self):
        def failing(*args, **kwargs):
            raise places.PlacesError("down", transient=True)

        box = agent_tools.ToolBox(context([]), failing, uniform_matrix(5))
        text, is_error = box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        self.assertTrue(is_error)
        self.assertIn("down", text)

    def test_travel_time_matrix(self):
        box, _ = toolbox([place("a")], minutes=12)
        box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        text, is_error = box.run("get_travel_time", {"nodes": ["origin", "a", "destination"]})
        self.assertFalse(is_error)
        minutes = json.loads(text)["minutes"]
        self.assertEqual(minutes["origin"]["a"], 12)
        self.assertNotIn("origin", minutes["origin"])

    def test_travel_time_rejects_unknown_and_duplicate_nodes(self):
        box, _ = toolbox([])
        self.assertTrue(box.run("get_travel_time", {"nodes": ["origin", "ghost"]})[1])
        self.assertTrue(box.run("get_travel_time", {"nodes": ["origin", "origin"]})[1])
        self.assertTrue(box.run("get_travel_time", {"nodes": ["origin"]})[1])

    def test_submit_accepts_and_records_reasons(self):
        box, _ = toolbox([place("a")])
        box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        text, is_error = box.run(
            "submit_itinerary",
            {"stops": [{"place_id": "a", "visit_minutes": 40, "why": "A calm  park"}], "summary": "Easy walk"},
        )
        self.assertFalse(is_error, text)
        self.assertTrue(box.finished)
        self.assertEqual(box.itinerary["stops"][0]["why"], "A calm park")
        self.assertEqual(box.itinerary["summary"], "Easy walk")

    def test_submit_reports_problems_then_gives_up(self):
        box, _ = toolbox([place("a")])
        for attempt in range(agent_tools.MAX_SUBMISSIONS):
            text, is_error = box.run("submit_itinerary", {"stops": [{"place_id": "nope"}], "summary": ""})
            self.assertTrue(is_error)
            self.assertIn("Rejected", text)
        self.assertTrue(box.finished)
        self.assertIsNone(box.itinerary)
        self.assertTrue(box.run("submit_itinerary", {"stops": [{"place_id": "a"}], "summary": ""})[1])

    def test_unknown_tool_and_bad_arguments(self):
        box, _ = toolbox([])
        self.assertTrue(box.run("delete_everything", {})[1])
        self.assertTrue(box.run("search_places", "oops")[1])

    def test_tool_definitions_match_the_handlers(self):
        names = [tool["name"] for tool in agent_tools.TOOLS]
        self.assertEqual(names, ["search_places", "get_travel_time", "submit_itinerary"])
        for tool in agent_tools.TOOLS:
            self.assertEqual(tool["input_schema"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
