import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import budget


class ComputeFreeTimeTests(unittest.TestCase):
    def test_plenty_of_time(self):
        result = budget.compute_free_time(180, 60)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["buffer_minutes"], 15)
        self.assertEqual(result["free_minutes"], 105)

    def test_buffer_grows_with_long_drives(self):
        result = budget.compute_free_time(400, 240)
        self.assertEqual(result["buffer_minutes"], 24)
        self.assertEqual(result["free_minutes"], 136)

    def test_exactly_minimum_free_time_is_ok(self):
        self.assertEqual(budget.compute_free_time(120, 60)["status"], "ok")

    def test_one_minute_short_goes_direct(self):
        result = budget.compute_free_time(119, 60)
        self.assertEqual(result["status"], "go_direct")
        self.assertEqual(result["free_minutes"], 44)

    def test_can_arrive_but_no_buffer(self):
        result = budget.compute_free_time(65, 60)
        self.assertEqual(result["status"], "go_direct")
        self.assertEqual(result["free_minutes"], 0)

    def test_impossible(self):
        result = budget.compute_free_time(30, 60)
        self.assertEqual(result["status"], "impossible")
        self.assertEqual(result["free_minutes"], 0)


class PlanBudgetTests(unittest.TestCase):
    def test_uses_time_difference(self):
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        result = budget.plan_budget(now + timedelta(hours=3), now, 60)
        self.assertEqual(result["free_minutes"], 105)

    def test_offsets_are_respected(self):
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        arrive = datetime(2026, 9, 20, 18, 0, tzinfo=timezone(timedelta(hours=3)))
        result = budget.plan_budget(arrive, now, 60)
        self.assertEqual(result["free_minutes"], 105)

    def test_rejects_naive_datetimes(self):
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            budget.plan_budget(datetime(2026, 9, 20, 15, 0), now, 60)


class ParseArriveByTests(unittest.TestCase):
    def test_parses_utc_z_suffix(self):
        parsed = budget.parse_arrive_by("2026-09-20T15:00:00.000Z")
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_rejects_missing_offset(self):
        with self.assertRaises(ValueError):
            budget.parse_arrive_by("2026-09-20T15:00:00")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            budget.parse_arrive_by("tomorrow")


if __name__ == "__main__":
    unittest.main()
