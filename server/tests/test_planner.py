import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import planner

ALWAYS_OPEN = [{"open": {"day": 0, "hour": 0, "minute": 0}}]
NOW = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)  # Sunday 12:00 in Israel (UTC+3)
BUFFER = 15


def place(place_id, rating=4.6, count=1000, types=("park",), periods=ALWAYS_OPEN, status="OPERATIONAL", primary=None):
    return {
        "id": place_id,
        "name": place_id.upper(),
        "lat": 32.0,
        "lon": 34.8,
        "types": list(types),
        "primary_type": primary or types[0],
        "rating": rating,
        "rating_count": count,
        "business_status": status,
        "periods": periods,
        "utc_offset_minutes": 180,
    }


def matrix_for(count, direct=30, origin_to=10, to_dest=10, between=5):
    size = count + 2
    grid = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            if i != j:
                grid[i][j] = between
    grid[planner.ORIGIN][planner.DESTINATION] = direct
    for c in range(planner.FIRST_CANDIDATE, size):
        grid[planner.ORIGIN][c] = origin_to
        grid[c][planner.DESTINATION] = to_dest
    return grid


def plan(candidates, matrix, hours_until_deadline=3):
    return planner.plan_stops(candidates, matrix, NOW, NOW + timedelta(hours=hours_until_deadline), BUFFER)


class SelectCandidatesTests(unittest.TestCase):
    def test_keeps_good_places(self):
        self.assertEqual([p["id"] for p in planner.select_candidates([place("a")])], ["a"])

    def test_drops_low_rating_and_few_reviews(self):
        found = planner.select_candidates([place("low", rating=3.9), place("few", count=99), place("ok")])
        self.assertEqual([p["id"] for p in found], ["ok"])

    def test_drops_unknown_hours(self):
        no_periods = place("none", periods=None)
        self.assertEqual(planner.select_candidates([no_periods]), [])

    def test_drops_places_that_are_not_operational(self):
        found = planner.select_candidates([place("closed", status="CLOSED_PERMANENTLY"), place("ok")])
        self.assertEqual([p["id"] for p in found], ["ok"])

    def test_drops_excluded_types(self):
        self.assertEqual(planner.select_candidates([place("pub", types=("bar", "park"))]), [])

    def test_removes_duplicates_and_sorts_by_quality(self):
        found = planner.select_candidates([place("b", rating=4.2), place("a", rating=4.8), place("b", rating=4.9)])
        self.assertEqual([p["id"] for p in found], ["a", "b"])

    def test_caps_the_number_of_candidates(self):
        many = [place(f"p{i:03d}") for i in range(100)]
        self.assertEqual(len(planner.select_candidates(many)), planner.MAX_CANDIDATES)


class VisitMinutesTests(unittest.TestCase):
    def test_uses_the_primary_type_first(self):
        self.assertEqual(planner.visit_minutes(place("m", types=("tourist_attraction", "museum"), primary="museum")), 90)

    def test_falls_back_to_other_types_and_then_default(self):
        self.assertEqual(planner.visit_minutes(place("g", types=("point_of_interest", "park"), primary="market")), 45)
        self.assertEqual(planner.visit_minutes(place("x", types=("market",), primary="market")), planner.DEFAULT_VISIT_MINUTES)


class PlanStopsTests(unittest.TestCase):
    def test_single_stop_timeline_adds_up(self):
        result = plan([place("a")], matrix_for(1), hours_until_deadline=2)
        stop = result["stops"][0]
        self.assertEqual(stop["arrive"], NOW + timedelta(minutes=10))
        self.assertEqual(stop["leave"], stop["arrive"] + timedelta(minutes=45))
        self.assertEqual(result["arrive_destination"], stop["leave"] + timedelta(minutes=10))
        self.assertEqual(result["final_drive_minutes"], 10)

    def test_arrives_before_the_deadline_minus_buffer(self):
        candidates = [place(f"p{i}") for i in range(6)]
        for hours in (1, 2, 4, 8):
            result = plan(candidates, matrix_for(6), hours_until_deadline=hours)
            if result:
                self.assertLessEqual(
                    result["arrive_destination"], NOW + timedelta(hours=hours) - timedelta(minutes=BUFFER)
                )

    def test_limits_the_number_of_stops(self):
        candidates = [place(f"p{i}") for i in range(8)]
        result = plan(candidates, matrix_for(8), hours_until_deadline=10)
        self.assertEqual(len(result["stops"]), planner.MAX_STOPS)

    def test_prefers_the_better_place_when_only_one_fits(self):
        candidates = [place("plain", rating=4.2, count=150), place("great", rating=4.9, count=5000)]
        result = plan(candidates, matrix_for(2), hours_until_deadline=1.5)
        self.assertEqual([s["place"]["id"] for s in result["stops"]], ["great"])

    def test_prefers_less_driving_when_quality_is_equal(self):
        candidates = [place("far"), place("near")]
        grid = matrix_for(2)
        grid[planner.ORIGIN][planner.FIRST_CANDIDATE] = 25
        grid[planner.FIRST_CANDIDATE][planner.DESTINATION] = 25
        result = plan(candidates, grid, hours_until_deadline=1.5)
        self.assertEqual([s["place"]["id"] for s in result["stops"]], ["near"])

    def test_skips_places_that_are_closed_at_the_visit_time(self):
        monday_only = [{"open": {"day": 1, "hour": 10, "minute": 0}, "close": {"day": 1, "hour": 18, "minute": 0}}]
        candidates = [place("closed", rating=4.9, count=9000, periods=monday_only), place("open", rating=4.2, count=150)]
        result = plan(candidates, matrix_for(2), hours_until_deadline=1.5)
        self.assertEqual([s["place"]["id"] for s in result["stops"]], ["open"])

    def test_skips_places_that_would_close_during_the_visit(self):
        closes_soon = [{"open": {"day": 0, "hour": 8, "minute": 0}, "close": {"day": 0, "hour": 12, "minute": 30}}]
        result = plan([place("late", periods=closes_soon)], matrix_for(1), hours_until_deadline=2)
        self.assertIsNone(result)

    def test_skips_unroutable_candidates(self):
        grid = matrix_for(2)
        grid[planner.ORIGIN][planner.FIRST_CANDIDATE] = None
        result = plan([place("island", rating=4.9, count=9000), place("ok")], grid, hours_until_deadline=1.5)
        self.assertEqual([s["place"]["id"] for s in result["stops"]], ["ok"])

    def test_returns_none_when_nothing_fits(self):
        grid = matrix_for(2, origin_to=200, to_dest=200)
        self.assertIsNone(plan([place("a"), place("b")], grid))

    def test_returns_none_without_candidates(self):
        self.assertIsNone(plan([], matrix_for(0)))

    def test_is_deterministic(self):
        candidates = [place(f"p{i}", rating=4.5 + i / 100) for i in range(6)]
        first = plan(candidates, matrix_for(6), hours_until_deadline=5)
        second = plan(candidates, matrix_for(6), hours_until_deadline=5)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
