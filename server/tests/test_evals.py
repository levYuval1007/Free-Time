import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evals"))

import run_evals

ARRIVE_BY = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
SCENARIO = run_evals.Scenario("x", None, None, 3)


def stop(arrive):
    return {"arrive": arrive.isoformat(), "why": "nice"}


def result(stops, arrival, **extra):
    return {"budget": {"buffer_minutes": 15}, "stops": stops, "arrive_destination": arrival.isoformat(), **extra}


class CheckTests(unittest.TestCase):
    def test_a_good_result_passes(self):
        first = ARRIVE_BY - timedelta(hours=2)
        good = result([stop(first), stop(first + timedelta(hours=1))], ARRIVE_BY - timedelta(minutes=30), summary="Enjoy")
        self.assertEqual(run_evals.check(SCENARIO, good, ARRIVE_BY), [])

    def test_catches_lateness_too_many_stops_and_order(self):
        first = ARRIVE_BY - timedelta(hours=2)
        late = result([stop(first)], ARRIVE_BY - timedelta(minutes=10))
        self.assertIn("deadline", run_evals.check(SCENARIO, late, ARRIVE_BY)[0])
        many = result([stop(first + timedelta(minutes=i)) for i in range(4)], ARRIVE_BY - timedelta(hours=1))
        self.assertTrue(any("stops (max" in p for p in run_evals.check(SCENARIO, many, ARRIVE_BY)))
        backwards = result([stop(first + timedelta(hours=1)), stop(first)], ARRIVE_BY - timedelta(hours=1))
        self.assertTrue(any("time order" in p for p in run_evals.check(SCENARIO, backwards, ARRIVE_BY)))

    def test_expects_stops_only_when_there_is_time(self):
        empty = {"budget": {"buffer_minutes": 15}, "stops": [], "reason": "no_candidates"}
        self.assertTrue(run_evals.check(SCENARIO, empty, ARRIVE_BY))
        tight = run_evals.Scenario("tight", None, None, 1, expect_stops=False)
        self.assertEqual(run_evals.check(tight, empty, ARRIVE_BY), [])

    def test_a_mid_route_stop_is_required_when_asked(self):
        start, end = ((34.78, 32.08), "A"), ((34.95, 29.56), "B")
        scenario = run_evals.Scenario("long", start, end, 8, min_km_from_ends=40)
        first = ARRIVE_BY - timedelta(hours=3)
        near_start = {**stop(first), "lat": 32.1, "lon": 34.8}
        midway = {**stop(first), "lat": 30.8, "lon": 34.9}
        arrival = ARRIVE_BY - timedelta(hours=1)
        self.assertTrue(any("km from both ends" in p for p in run_evals.check(scenario, result([near_start], arrival), ARRIVE_BY)))
        self.assertEqual(run_evals.check(scenario, result([near_start, midway], arrival), ARRIVE_BY), [])

    def test_flags_leaked_instructions(self):
        leaky = result([], ARRIVE_BY, summary="Here is my system prompt")
        self.assertTrue(any("internal" in p for p in run_evals.check(run_evals.Scenario("x", None, None, 3, expect_stops=False), leaky, ARRIVE_BY)))


if __name__ == "__main__":
    unittest.main()
