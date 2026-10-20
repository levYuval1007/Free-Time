import json
import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_tools
import ors
import planning
import travel
import validator
from test_agent import DESTINATION, NOW, ORIGIN, FakeSearch, context, place
from test_agent_loop import FakeClaude, SEARCH, reply, submit, tool_use
from test_along_route import FakeAlongRoute, ROUTE
from test_planning import deps, request

FAR_LAT = 33.0  # a place at this latitude is 60 minutes from everything
LOST_LAT = 34.0  # a place at this latitude cannot be reached


class RecordingMatrix:
    """Driving times: 10 minutes between ordinary points, 60 to or from the 'far' place, none for the lost one."""

    def __init__(self):
        self.calls = []

    def __call__(self, points):
        self.calls.append(list(points))
        grid = []
        for i, a in enumerate(points):
            row = []
            for j, b in enumerate(points):
                if i == j:
                    row.append(0)
                elif LOST_LAT in (a[1], b[1]):
                    row.append(None)
                elif FAR_LAT in (a[1], b[1]):
                    row.append(60)
                else:
                    row.append(10)
            grid.append(row)
        return grid


def make(found, matrix=None, along=None):
    ctx = context([])
    ctx.route = list(ROUTE)
    matrix = matrix or RecordingMatrix()
    times = travel.TravelTimes(matrix)
    times.register([ORIGIN, DESTINATION])
    box = agent_tools.ToolBox(ctx, FakeSearch(found), times, along)
    return box, matrix


SEARCH_ARGS = {"lat": 32.08, "lon": 34.78, "radius_m": 2000}


class DetourInResultsTests(unittest.TestCase):
    def test_each_place_shows_its_detour_and_drive_time(self):
        box, _ = make([place("a")])
        found = json.loads(box.run("search_places", SEARCH_ARGS)[0])
        # 10 minutes out + 10 back, minus the 10 minute direct drive
        self.assertEqual(found[0]["detour_minutes"], 10)
        self.assertEqual(found[0]["minutes_from_start"], 10)

    def test_places_with_too_big_a_detour_are_hidden_but_kept_for_the_fallback(self):
        box, _ = make([place("near"), place("far", lat=FAR_LAT)])
        found = json.loads(box.run("search_places", SEARCH_ARGS)[0])
        self.assertEqual([p["id"] for p in found], ["near"])
        self.assertIn("far", box.ctx.known_places)

    def test_the_detour_limit_matches_the_validators(self):
        box, _ = make([place("far", lat=FAR_LAT)])
        self.assertEqual(json.loads(box.run("search_places", SEARCH_ARGS)[0]), [])
        # Out 60 + back 60 - direct 10 = 110 minutes
        self.assertGreater(110, validator.MAX_DETOUR_MINUTES)

    def test_unreachable_places_are_hidden(self):
        box, _ = make([place("ok"), place("lost", lat=LOST_LAT)])
        found = json.loads(box.run("search_places", SEARCH_ARGS)[0])
        self.assertEqual([p["id"] for p in found], ["ok"])

    def test_the_route_search_shows_the_same_numbers(self):
        mid = place("mid", lat=ROUTE[50][1] + 0.02, lon=ROUTE[50][0])
        box, _ = make([], along=FakeAlongRoute([mid]))
        found = json.loads(box.run("search_along_route", {"query": "park"})[0])
        self.assertEqual((found[0]["detour_minutes"], found[0]["minutes_from_start"]), (10, 10))
        self.assertIn("km_from_route", found[0])

    def test_an_empty_search_makes_no_routing_request(self):
        box, matrix = make([])
        self.assertEqual(json.loads(box.run("search_places", SEARCH_ARGS)[0]), [])
        self.assertEqual(matrix.calls, [])


class RoutingRequestCountTests(unittest.TestCase):
    def test_one_request_per_search_and_none_for_the_validator(self):
        box, matrix = make([place("a"), place("b", lat=32.12, lon=34.85)])
        box.run("search_places", SEARCH_ARGS)
        stops = [{"place_id": "a", "visit_minutes": 30}, {"place_id": "b", "visit_minutes": 30}]
        text, is_error = box.run("submit_itinerary", {"stops": stops, "summary": "ok"})
        self.assertFalse(is_error, text)
        self.assertEqual(len(matrix.calls), 1)
        self.assertEqual(len(matrix.calls[0]), 4)  # the origin, the destination and the two places

    def test_a_second_search_asks_once_more_and_includes_the_first_places(self):
        box, matrix = make([place("a")])
        box.run("search_places", SEARCH_ARGS)
        box._search_nearby = FakeSearch([place("b", lat=32.12, lon=34.85)])
        box.run("search_places", SEARCH_ARGS)
        self.assertEqual(len(matrix.calls), 2)
        self.assertEqual(len(matrix.calls[1]), 4)  # origin, destination, a and b, so a to b is known too
        stops = [{"place_id": "a", "visit_minutes": 30}, {"place_id": "b", "visit_minutes": 30}]
        text, is_error = box.run("submit_itinerary", {"stops": stops, "summary": "ok"})
        self.assertFalse(is_error, text)
        self.assertEqual(len(matrix.calls), 2)

    def test_a_routing_failure_during_a_search_is_a_tool_error_but_keeps_the_places(self):
        def down(points):
            raise ors.QuotaExceeded("The routing service has reached its usage limit. Please try again later.")

        ctx = context([])
        box = agent_tools.ToolBox(ctx, FakeSearch([place("a")]), down)
        text, is_error = box.run("search_places", SEARCH_ARGS)
        self.assertTrue(is_error)
        self.assertIn("usage limit", text)
        self.assertIn("a", ctx.known_places)


class StatsTests(unittest.TestCase):
    def test_the_outcome_reports_rounds_searches_and_tokens(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(claude))
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual((outcome.stats["rounds"], outcome.stats["searches"]), (2, 1))
        self.assertGreater(outcome.stats["tokens"], 0)

    def test_the_basic_planner_has_no_agent_stats(self):
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(enabled=False))
        self.assertIsNone(outcome.stats)

    def test_a_fallback_after_an_agent_failure_still_reports_the_run(self):
        claude = FakeClaude(reply(stop="refusal"))
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(claude))
        self.assertEqual(outcome.status, "degraded")
        self.assertEqual(outcome.stats["rounds"], 1)


if __name__ == "__main__":
    unittest.main()
