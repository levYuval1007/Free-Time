import json
import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_tools
import geo
import places
import planning
import validator
from test_agent import DESTINATION, NOW, ORIGIN, FakeSearch, context, place, uniform_matrix
from test_agent_loop import DEADLINE, FakeClaude, reply, submit, tool_use
from test_places import RAW_PLACE, PlacesTestBase, ok_response
from test_planning import deps, request

# A straight route from Tel Aviv towards Jerusalem, with a point every 0.01 degrees.
ROUTE = [(34.78 + 0.0043 * i, 32.08 - 0.0031 * i) for i in range(101)]


class GeoTests(unittest.TestCase):
    def test_polyline_matches_googles_documented_example(self):
        route = [(-120.2, 38.5), (-120.95, 40.7), (-126.453, 43.252)]
        self.assertEqual(geo.encode_polyline(route), "_p~iF~ps|U_ulLnnqC_mqNvxq`@")

    def test_empty_route_encodes_to_an_empty_string(self):
        self.assertEqual(geo.encode_polyline([]), "")

    def test_thinning_keeps_the_ends_and_the_limit(self):
        long_route = [(34.0 + i * 0.001, 32.0 + i * 0.0005) for i in range(2000)]
        thin = geo.thin(long_route, 200)
        self.assertLessEqual(len(thin), 200)
        self.assertGreater(len(thin), 150)
        self.assertEqual((thin[0], thin[-1]), (long_route[0], long_route[-1]))

    def test_short_routes_are_not_thinned(self):
        self.assertEqual(geo.thin(ROUTE[:10], 200), ROUTE[:10])

    def test_distance_to_route(self):
        straight = [(34.0, 32.0), (35.0, 32.0)]
        # 0.1 degrees of latitude is about 11.1 km
        self.assertAlmostEqual(geo.distance_to_route_km(32.1, 34.5, straight), 11.1, delta=0.2)
        self.assertAlmostEqual(geo.distance_to_route_km(32.0, 34.5, straight), 0.0, delta=0.01)
        # Beyond the end the nearest point is the end of the route.
        self.assertAlmostEqual(geo.distance_to_route_km(32.0, 35.1, straight), 9.4, delta=0.3)
        self.assertIsNone(geo.distance_to_route_km(32.0, 34.0, []))


class SearchAlongRouteRequestTests(PlacesTestBase):
    def test_request_carries_the_query_polyline_and_key(self):
        self.client.request.return_value = ok_response(RAW_PLACE)
        found = places.search_along_route("abc", "scenic viewpoint")
        method, path, body, headers = self.client.request.call_args.args
        self.assertEqual((method, path), ("POST", "/v1/places:searchText"))
        sent = json.loads(body)
        self.assertEqual(sent["textQuery"], "scenic viewpoint")
        self.assertEqual(sent["searchAlongRouteParameters"]["polyline"]["encodedPolyline"], "abc")
        self.assertEqual(sent["pageSize"], 20)
        self.assertEqual(headers["X-Goog-Api-Key"], "test-key")
        self.assertNotIn("test-key", path)
        self.assertIn("places.regularOpeningHours", headers["X-Goog-FieldMask"])
        self.assertEqual([p["id"] for p in found], ["abc123"])

    def test_the_search_is_counted_as_a_billed_request(self):
        before = places.stats()
        self.client.request.return_value = ok_response(RAW_PLACE)
        places.search_along_route("abc", "park")
        after = places.stats()
        self.assertEqual(after["requests"], before["requests"] + 1)
        self.assertGreater(after["estimated_cost_usd"], before["estimated_cost_usd"])


class FakeAlongRoute:
    def __init__(self, found):
        self.found = found
        self.calls = []

    def __call__(self, polyline, query):
        self.calls.append((polyline, query))
        return self.found


def at(place_id, lat, lon, **kwargs):
    found = place(place_id, lat=lat, lon=lon, **kwargs)
    return found


MIDWAY = ROUTE[50]  # (lon, lat)


def toolbox(found, route=ROUTE, with_search=True):
    ctx = context([])
    ctx.route = list(route)
    along = FakeAlongRoute(found)
    box = agent_tools.ToolBox(ctx, FakeSearch([]), uniform_matrix(10), along if with_search else None)
    return box, along


class SearchAlongRouteToolTests(unittest.TestCase):
    def test_returns_places_with_their_distance_from_the_road_and_remembers_them(self):
        box, along = toolbox([at("mid", MIDWAY[1] + 0.02, MIDWAY[0])])
        text, is_error = box.run("search_along_route", {"query": "  scenic   viewpoint "})
        self.assertFalse(is_error, text)
        found = json.loads(text)
        self.assertEqual([p["id"] for p in found], ["mid"])
        # 0.02 degrees north is 2.2 km, but the road slopes, so the perpendicular distance is about 1.7 km
        self.assertAlmostEqual(found[0]["km_from_route"], 1.7, delta=0.2)
        self.assertIn("mid", box.ctx.known_places)
        self.assertEqual(along.calls[0][1], "scenic viewpoint")
        self.assertTrue(along.calls[0][0])  # the encoded route was sent

    def test_drops_places_that_are_too_far_from_the_route(self):
        far = at("far", MIDWAY[1] + 0.4, MIDWAY[0])  # about 44 km north of the road
        near = at("near", MIDWAY[1] + 0.05, MIDWAY[0])
        box, _ = toolbox([far, near])
        found = json.loads(box.run("search_along_route", {"query": "park"})[0])
        self.assertEqual([p["id"] for p in found], ["near"])
        self.assertNotIn("far", box.ctx.known_places)

    def test_keeps_the_quality_rules(self):
        weak = at("weak", MIDWAY[1], MIDWAY[0], rating=3.0)
        box, _ = toolbox([weak])
        self.assertEqual(json.loads(box.run("search_along_route", {"query": "park"})[0]), [])

    def test_the_route_is_thinned_before_it_is_sent(self):
        long_route = [(34.0 + i * 0.0005, 32.0 - i * 0.0003) for i in range(3000)]
        box, along = toolbox([], route=long_route)
        box.run("search_along_route", {"query": "park"})
        decoded_points = len(along.calls[0][0])
        self.assertLess(decoded_points, 3000)  # an encoded point takes several characters, so this is generous

    def test_shares_the_search_limit_with_the_other_search_tool(self):
        box, _ = toolbox([])
        for _ in range(agent_tools.MAX_SEARCHES - 1):
            self.assertFalse(box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})[1])
        self.assertFalse(box.run("search_along_route", {"query": "park"})[1])
        self.assertTrue(box.run("search_along_route", {"query": "park"})[1])
        self.assertTrue(box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})[1])

    def test_rejects_bad_queries_without_calling_google(self):
        box, along = toolbox([])
        for args in ({"query": ""}, {"query": "a"}, {"query": 5}, {}):
            self.assertTrue(box.run("search_along_route", args)[1], args)
        self.assertEqual(along.calls, [])

    def test_is_unavailable_without_a_route_or_search_function(self):
        for box in (toolbox([], route=[])[0], toolbox([], with_search=False)[0]):
            text, is_error = box.run("search_along_route", {"query": "park"})
            self.assertTrue(is_error)
            self.assertIn("search_places", text)

    def test_places_failure_becomes_a_tool_error(self):
        def failing(polyline, query):
            raise places.PlacesError("down", transient=True)

        ctx = context([])
        ctx.route = list(ROUTE)
        box = agent_tools.ToolBox(ctx, FakeSearch([]), uniform_matrix(10), failing)
        text, is_error = box.run("search_along_route", {"query": "park"})
        self.assertTrue(is_error)
        self.assertIn("down", text)

    def test_search_places_results_also_show_the_distance_from_the_road(self):
        ctx = context([])
        ctx.route = list(ROUTE)
        box = agent_tools.ToolBox(ctx, FakeSearch([at("near", ROUTE[0][1] + 0.01, ROUTE[0][0])]), uniform_matrix(10))
        found = json.loads(box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})[0])
        self.assertIn("km_from_route", found[0])

    def test_no_distance_is_shown_when_there_is_no_route(self):
        ctx = context([])
        box = agent_tools.ToolBox(ctx, FakeSearch([place("a")]), uniform_matrix(10))
        found = json.loads(box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})[0])
        self.assertNotIn("km_from_route", found[0])


class DetourRuleTests(unittest.TestCase):
    """The matrix below makes the stop 'x' a detour of `detour` minutes: origin to x and x to the destination
    add up to the direct drive (30) plus the detour."""

    def matrix_with_detour(self, detour):
        def matrix(points):
            size = len(points)
            grid = [[0 if i == j else 5 for j in range(size)] for i in range(size)]
            grid[0][size - 1] = 30
            half = (30 + detour) / 2
            for i in range(1, size - 1):
                grid[0][i] = half
                grid[i][size - 1] = half
            return grid

        return matrix

    def check(self, detour):
        ctx = context([place("x")], deadline_minutes=600)
        return validator.validate_itinerary(ctx, [{"place_id": "x", "visit_minutes": 30}], self.matrix_with_detour(detour))

    def test_a_small_detour_is_accepted(self):
        result, errors = self.check(validator.MAX_DETOUR_MINUTES)
        self.assertEqual(errors, [])
        self.assertEqual(len(result["stops"]), 1)

    def test_a_large_detour_is_rejected_with_the_numbers(self):
        _, errors = self.check(validator.MAX_DETOUR_MINUTES + 10)
        self.assertEqual(len(errors), 1)
        self.assertIn("30 minutes", errors[0])
        self.assertIn(str(validator.MAX_DETOUR_MINUTES), errors[0])

    def test_unroutable_legs_do_not_crash_the_check(self):
        def matrix(points):
            grid = [[10] * len(points) for _ in points]
            grid[0][-1] = None
            return grid

        ctx = context([place("x")])
        _, errors = validator.validate_itinerary(ctx, [{"place_id": "x"}], matrix)
        self.assertEqual([e for e in errors if "adds about" in e], [])


class PlanningRouteTests(unittest.TestCase):
    def test_the_agent_gets_the_direct_route_and_the_along_route_search(self):
        along = FakeAlongRoute([at("mid", MIDWAY[1] + 0.02, MIDWAY[0])])
        claude = FakeClaude(
            reply(tool_use("t1", "search_along_route", query="park")),
            reply(submit("t2", place_id="mid")),
        )
        d = deps(claude)
        d.direct_route = lambda *coordinates: {"minutes": 10, "geometry": [list(point) for point in ROUTE]}
        d.search_along_route = along
        outcome = planning.execute_plan(request("quiet"), lambda text: None, NOW, d)
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(outcome.result["stops"][0]["id"], "mid")
        self.assertEqual(len(along.calls), 1)
        names = [tool["name"] for tool in claude.calls[0]["tools"]]
        self.assertIn("search_along_route", names)

    def test_compute_free_time_returns_the_route(self):
        d = deps()
        d.direct_route = lambda *coordinates: {"minutes": 10, "geometry": [[34.8, 32.1], [35.2, 31.8]]}
        direct_minutes, free_time, route = planning.compute_free_time(request(), NOW, d)
        self.assertEqual(direct_minutes, 10)
        self.assertEqual(route, [(34.8, 32.1), (35.2, 31.8)])
        self.assertEqual(free_time["status"], "ok")

    def test_a_route_without_geometry_gives_an_empty_route(self):
        d = deps()
        d.direct_route = lambda *coordinates: {"minutes": 10}
        self.assertEqual(planning.compute_free_time(request(), NOW, d)[2], [])


if __name__ == "__main__":
    unittest.main()
