import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import limits
import planning
from test_agent import DESTINATION, NOW, ORIGIN, FakeSearch, place, uniform_matrix
from test_agent_loop import DEADLINE, SEARCH, FakeClaude, reply, submit, text_block, tool_use


def deps(claude=None, found=None, enabled=True, minutes=10, search=None, guard=None):
    guard = guard or limits.Guard()
    search = search or FakeSearch(found if found is not None else [place("a"), place("b")])
    return planning.Deps(
        search_nearby=search,
        travel_matrix=uniform_matrix(minutes),
        direct_route=lambda *coordinates: {"minutes": minutes},
        route_through=lambda points: {"geometry": [[p[0], p[1]] for p in points], "steps": []},
        make_client=lambda: claude,
        agent_enabled=lambda: enabled,
        budget_ok=guard.agent_allowed,
        record_usage=guard.record_usage,
    )


def request(preferences="", deadline=DEADLINE):
    return planning.PlanRequest(
        origin=ORIGIN, destination=DESTINATION, arrive_by=deadline, preferences=preferences,
        origin_label="Tel Aviv", destination_label="Jerusalem",
    )


class ExecutePlanTests(unittest.TestCase):
    def test_agent_success(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        stages = []
        outcome = planning.execute_plan(request("quiet"), stages.append, NOW, deps(claude))
        self.assertEqual(outcome.status, "succeeded")
        result = outcome.result
        self.assertEqual(result["source"], "agent")
        self.assertEqual(result["summary"], "Enjoy")
        self.assertEqual(result["stops"][0]["id"], "a")
        self.assertEqual(result["stops"][0]["why"], "nice")
        self.assertEqual(len(result["geometry"]), 3)  # origin, one stop, destination
        self.assertIn("quiet", claude.calls[0]["messages"][0]["content"])
        self.assertEqual(stages, ["Checking your route", "Choosing places", "Searching for places", "Checking the plan"])

    def test_agent_failure_falls_back_using_places_it_already_found(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(text_block("no idea"), stop="end_turn"))
        search = FakeSearch([place("a"), place("b")])
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(claude, search=search))
        self.assertEqual(outcome.status, "degraded")
        self.assertEqual(outcome.degraded_reason, "no_itinerary_submitted")
        self.assertEqual(outcome.result["source"], "baseline")
        self.assertTrue(outcome.result["stops"])
        self.assertEqual(len(search.calls), 1)  # the fallback did not pay for another search

    def test_fallback_searches_when_the_agent_found_nothing(self):
        claude = FakeClaude(reply(stop="refusal"))
        search = FakeSearch([place("a")])
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(claude, search=search))
        self.assertEqual((outcome.status, outcome.degraded_reason), ("degraded", "refused"))
        self.assertTrue(outcome.result["stops"])
        self.assertEqual(len(search.calls), 2)  # near the start and near the destination

    def test_missing_client_degrades_instead_of_failing(self):
        def broken():
            raise RuntimeError("no key")

        d = deps()
        d.make_client = broken
        outcome = planning.execute_plan(request(), lambda text: None, NOW, d)
        self.assertEqual((outcome.status, outcome.degraded_reason), ("degraded", "llm_unavailable"))
        self.assertTrue(outcome.result["stops"])

    def test_agent_disabled_uses_the_basic_planner_without_degrading(self):
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(enabled=False))
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(outcome.result["source"], "baseline")

    def test_no_free_time_skips_the_agent(self):
        class Boom:
            def __getattr__(self, name):
                raise AssertionError("Claude must not be called")

        outcome = planning.execute_plan(
            request(deadline=NOW + timedelta(minutes=30)), lambda text: None, NOW, deps(Boom(), minutes=20)
        )
        self.assertEqual(outcome.status, "succeeded")
        self.assertEqual(outcome.result["reason"], "not_enough_time")
        self.assertEqual(outcome.result["stops"], [])

    def test_usage_is_recorded_against_the_daily_budget(self):
        guard = limits.Guard(per_ip_per_hour=1, plans_per_day=1, daily_tokens=100)
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        planning.execute_plan(request(), lambda text: None, NOW, deps(claude, guard=guard))
        self.assertGreater(guard.snapshot()["tokens_today"], 100)
        self.assertFalse(guard.agent_allowed())

    def test_spent_daily_budget_uses_the_basic_planner_without_calling_claude(self):
        class Boom:
            def __getattr__(self, name):
                raise AssertionError("Claude must not be called")

        guard = limits.Guard(per_ip_per_hour=1, plans_per_day=1, daily_tokens=10)
        guard.record_usage({"input_tokens": 50})
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(Boom(), guard=guard))
        self.assertEqual((outcome.status, outcome.degraded_reason), ("degraded", "daily_budget"))
        self.assertTrue(outcome.result["stops"])

    def test_nothing_suitable_is_reported_not_failed(self):
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(enabled=False, found=[]))
        self.assertEqual(outcome.result["reason"], "no_candidates")


if __name__ == "__main__":
    unittest.main()
