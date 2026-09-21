import logging
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import limits


class Clock:
    def __init__(self, year=2026, month=9, day=21, hour=12):
        self.now = datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.now


class GuardTests(unittest.TestCase):
    def test_limits_plans_per_address_per_hour(self):
        clock = Clock()
        guard = limits.Guard(per_ip_per_hour=2, plans_per_day=100, daily_tokens=1, clock=clock)
        for _ in range(2):
            self.assertIsNone(guard.check_new_plan("1.1.1.1"))
            guard.count_plan("1.1.1.1")
        message, retry_after = guard.check_new_plan("1.1.1.1")
        self.assertIn("last hour", message)
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, 3600)
        self.assertIsNone(guard.check_new_plan("2.2.2.2"))  # other addresses are unaffected
        clock.now += 3601
        self.assertIsNone(guard.check_new_plan("1.1.1.1"))

    def test_checking_does_not_count(self):
        guard = limits.Guard(per_ip_per_hour=1, plans_per_day=100, daily_tokens=1, clock=Clock())
        for _ in range(5):
            self.assertIsNone(guard.check_new_plan("1.1.1.1"))

    def test_daily_plan_limit_resets_at_midnight_utc(self):
        clock = Clock(hour=23)
        guard = limits.Guard(per_ip_per_hour=100, plans_per_day=2, daily_tokens=1, clock=clock)
        guard.count_plan("a")
        guard.count_plan("b")
        message, retry_after = guard.check_new_plan("c")
        self.assertIn("today", message)
        self.assertLessEqual(retry_after, 3600)
        clock.now += 2 * 3600
        self.assertIsNone(guard.check_new_plan("c"))

    def test_daily_token_budget_switches_the_agent_off(self):
        clock = Clock()
        guard = limits.Guard(per_ip_per_hour=1, plans_per_day=1, daily_tokens=1000, clock=clock)
        self.assertTrue(guard.agent_allowed())
        guard.record_usage({"input_tokens": 600, "output_tokens": 300})
        self.assertTrue(guard.agent_allowed())
        guard.record_usage({"input_tokens": 50, "cache_read_tokens": 100})
        self.assertFalse(guard.agent_allowed())
        clock.now += 86400
        self.assertTrue(guard.agent_allowed())
        self.assertEqual(guard.snapshot()["tokens_today"], 0)


class CostTests(unittest.TestCase):
    USAGE = {"input_tokens": 1000, "output_tokens": 500, "cache_read_tokens": 200, "cache_write_tokens": 100}

    def setUp(self):
        self.names = [
            "ANTHROPIC_PRICE_INPUT_PER_MTOK",
            "ANTHROPIC_PRICE_OUTPUT_PER_MTOK",
            "ANTHROPIC_PRICE_CACHE_READ_PER_MTOK",
            "ANTHROPIC_PRICE_CACHE_WRITE_PER_MTOK",
        ]
        self.saved = {name: os.environ.pop(name, None) for name in self.names}

    def tearDown(self):
        for name, value in self.saved.items():
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value

    def test_total_tokens(self):
        self.assertEqual(limits.total_tokens(self.USAGE), 1800)

    def test_no_dollar_estimate_without_prices(self):
        self.assertIsNone(limits.claude_cost_usd(self.USAGE))
        line = limits.cost_line(self.USAGE, searches=2, rounds=3)
        self.assertIn("tokens=1800", line)
        self.assertIn("places_searches=2", line)
        self.assertIn("places_usd=0.07", line)
        self.assertNotIn("claude_usd", line)

    def test_dollar_estimate_with_prices(self):
        os.environ.update(
            {
                "ANTHROPIC_PRICE_INPUT_PER_MTOK": "1",
                "ANTHROPIC_PRICE_OUTPUT_PER_MTOK": "10",
                "ANTHROPIC_PRICE_CACHE_READ_PER_MTOK": "0.5",
                "ANTHROPIC_PRICE_CACHE_WRITE_PER_MTOK": "2",
            }
        )
        # 1000*1 + 500*10 + 200*0.5 + 100*2 = 6300 micro-dollars
        self.assertAlmostEqual(limits.claude_cost_usd(self.USAGE), 0.0063)
        self.assertIn("claude_usd=0.0063", limits.cost_line(self.USAGE, 0, 1))

    def test_bad_price_gives_no_estimate(self):
        os.environ["ANTHROPIC_PRICE_INPUT_PER_MTOK"] = "cheap"
        self.assertIsNone(limits.claude_cost_usd(self.USAGE))


class RedactionTests(unittest.TestCase):
    def redact(self, path):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s - %s %s HTTP/%s %d", ("1.2.3.4:0", "GET", path, "1.1", 200), None)
        limits.RedactQueryFilter().filter(record)
        return record.args[2]

    def test_locations_and_search_text_are_removed(self):
        redacted = self.redact("/api/suggest?q=Rehov+Herzl&session=abc-123&lat=32.6359&lon=35.0869")
        self.assertNotIn("Herzl", redacted)
        self.assertNotIn("32.6359", redacted)
        self.assertNotIn("35.0869", redacted)
        self.assertIn("session=abc-123", redacted)
        self.assertIn("lat=redacted", redacted)

    def test_route_coordinates_are_removed(self):
        redacted = self.redact("/api/route?from_lon=35.08&from_lat=32.63&to_lon=34.77&to_lat=32.08&arrive_by=2026-09-21T11%3A15")
        for value in ("35.08", "32.63", "34.77", "32.08"):
            self.assertNotIn(value, redacted)
        self.assertIn("arrive_by=2026", redacted)

    def test_paths_without_a_query_are_untouched(self):
        self.assertEqual(self.redact("/api/plans/abc123"), "/api/plans/abc123")


if __name__ == "__main__":
    unittest.main()
