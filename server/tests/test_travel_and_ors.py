import json
import os
import sys
import threading
import time
import unittest
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_tools
import ors
import travel
import validator
from test_agent import DESTINATION, NOW, ORIGIN, FakeSearch, place

A = (34.80, 32.10)
B = (34.90, 32.20)
C = (35.00, 32.30)


class CountingMatrix:
    """A fake routing matrix: 10 minutes between any two different points."""

    def __init__(self):
        self.calls = []

    def __call__(self, points):
        self.calls.append(list(points))
        return [[0 if i == j else 10 for j in range(len(points))] for i in range(len(points))]


class TravelTimesTests(unittest.TestCase):
    def test_answers_repeat_questions_from_memory(self):
        matrix = CountingMatrix()
        times = travel.TravelTimes(matrix)
        first = times([ORIGIN, A, DESTINATION])
        self.assertEqual(first[0][1], 10)
        self.assertEqual(first[1][1], 0)
        times([ORIGIN, A, DESTINATION])
        times([A, ORIGIN])
        self.assertEqual(len(matrix.calls), 1)

    def test_one_call_fills_in_every_known_point(self):
        matrix = CountingMatrix()
        times = travel.TravelTimes(matrix)
        times.register([ORIGIN, DESTINATION, A, B, C])
        times([ORIGIN, A])  # asks about two points, so everything known is fetched together
        self.assertEqual(len(matrix.calls[0]), 5)
        times([B, C, DESTINATION])
        self.assertEqual(len(matrix.calls), 1)

    def test_new_points_trigger_another_call_that_keeps_the_old_answers(self):
        matrix = CountingMatrix()
        times = travel.TravelTimes(matrix)
        times.register([ORIGIN, DESTINATION, A])
        times([ORIGIN, A])
        times.register([B])
        times([A, B])
        self.assertEqual(len(matrix.calls), 2)
        self.assertEqual(len(matrix.calls[1]), 4)
        times([ORIGIN, A, B, DESTINATION])
        self.assertEqual(len(matrix.calls), 2)

    def test_unroutable_pairs_are_remembered_as_none(self):
        calls = []

        def matrix(points):
            calls.append(points)
            return [[0, None], [5, 0]]

        times = travel.TravelTimes(matrix)
        self.assertIsNone(times([ORIGIN, A])[0][1])
        self.assertEqual(times([A, ORIGIN])[0][1], 5)
        self.assertEqual(len(calls), 1)

    def test_too_many_points_fall_back_to_the_requested_ones(self):
        matrix = CountingMatrix()
        times = travel.TravelTimes(matrix)
        many = [(34.0 + i / 100, 32.0) for i in range(travel.MAX_NODES + 5)]
        times.register(many)
        times([ORIGIN, DESTINATION])
        self.assertEqual(len(matrix.calls[0]), 2)


class RouteCacheAndErrorTests(unittest.TestCase):
    def setUp(self):
        ors._route_cache.clear()
        ors._route_locks.clear()

    def response(self, minutes=42):
        body = {
            "features": [
                {
                    "properties": {"summary": {"distance": 50000, "duration": minutes * 60}, "segments": [{"steps": []}]},
                    "geometry": {"coordinates": [[34.8, 32.1], [35.2, 31.8]]},
                }
            ]
        }
        return 200, json.dumps(body).encode()

    def test_the_same_route_is_fetched_once(self):
        with mock.patch.object(ors, "_key", return_value="k"), mock.patch.object(
            ors._client, "request", return_value=self.response()
        ) as request:
            first = ors.route_coords(34.8, 32.1, 35.2, 31.8)
            second = ors.route_coords(34.8, 32.1, 35.2, 31.8)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first["minutes"], 42)
        second["budget"] = "changed by a caller"
        self.assertNotIn("budget", first)

    def test_simultaneous_requests_share_one_call(self):
        def slow(*args, **kwargs):
            time.sleep(0.1)
            return self.response()

        results = []
        with mock.patch.object(ors, "_key", return_value="k"), mock.patch.object(
            ors._client, "request", side_effect=slow
        ) as request:
            threads = [
                threading.Thread(target=lambda: results.append(ors.route_coords(34.8, 32.1, 35.2, 31.8)))
                for _ in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(results), 4)

    def test_expired_answers_are_fetched_again(self):
        with mock.patch.object(ors, "_key", return_value="k"), mock.patch.object(
            ors._client, "request", return_value=self.response()
        ) as request:
            ors.route_coords(34.8, 32.1, 35.2, 31.8)
            for key, (expires, result) in list(ors._route_cache.items()):
                ors._route_cache[key] = (time.monotonic() - 1, result)
            ors.route_coords(34.8, 32.1, 35.2, 31.8)
        self.assertEqual(request.call_count, 2)

    def test_quota_errors_get_a_friendly_message(self):
        quota = (403, b'{ "error": "Quota exceeded" }')
        with mock.patch.object(ors._client, "request", return_value=quota):
            with self.assertRaises(ors.QuotaExceeded) as caught:
                ors._call("POST", "/v2/matrix/driving-car", b"{}")
        self.assertNotIn("403", str(caught.exception))
        self.assertNotIn("{", str(caught.exception))
        with mock.patch.object(ors._client, "request", return_value=(429, b"slow down")):
            with self.assertRaises(ors.QuotaExceeded):
                ors._call("GET", "/x")

    def test_other_errors_do_not_leak_the_response_body(self):
        with mock.patch.object(ors._client, "request", return_value=(500, b"stack trace with secrets")):
            with self.assertRaises(ors.RouteError) as caught:
                ors._call("GET", "/x")
        self.assertNotIn("secrets", str(caught.exception))
        self.assertNotIsInstance(caught.exception, ors.QuotaExceeded)


class ToolBoxRoutingTests(unittest.TestCase):
    def make(self, matrix):
        ctx = validator.TripContext(
            now=NOW, arrive_by=NOW + timedelta(hours=4), buffer_minutes=15, origin=ORIGIN, destination=DESTINATION
        )
        return agent_tools.ToolBox(ctx, FakeSearch([place("a"), place("b")]), matrix)

    def test_routing_failure_becomes_a_tool_error(self):
        def down(points):
            raise ors.QuotaExceeded("The routing service has reached its usage limit. Please try again later.")

        box = self.make(down)
        box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        text, is_error = box.run("get_travel_time", {"nodes": ["origin", "a"]})
        self.assertTrue(is_error)
        self.assertIn("usage limit", text)
        text, is_error = box.run("submit_itinerary", {"stops": [{"place_id": "a"}], "summary": ""})
        self.assertTrue(is_error)
        self.assertIn("routing service failed", text)

    def test_searches_register_places_so_one_call_covers_later_questions(self):
        counter = CountingMatrix()
        times = travel.TravelTimes(counter)
        times.register([ORIGIN, DESTINATION])
        box = self.make(times)
        box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        box.run("get_travel_time", {"nodes": ["origin", "a", "b"]})
        box.run("get_travel_time", {"nodes": ["a", "b", "destination"]})
        stops = [{"place_id": "a", "visit_minutes": 30}, {"place_id": "b", "visit_minutes": 30}]
        text, is_error = box.run("submit_itinerary", {"stops": stops, "summary": "ok"})
        self.assertFalse(is_error, text)
        self.assertEqual(len(counter.calls), 1)


if __name__ == "__main__":
    unittest.main()
