import os
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import comparison
import places
from test_agent import NOW, FakeSearch, place, uniform_matrix
from test_agent_loop import FakeClaude, make_box, reply, submit, tool_use

SEARCH_ARGS = {"lat": 32.08, "lon": 34.78, "radius_m": 3000}


def spend(cap=0.30, assumed=False):
    return comparison.Spend(cap, dict(comparison.ASSUMED_PRICES), assumed)


def usage(input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write,
    )


def candidates():
    return [
        place("coffee", types=("cafe",), lat=32.09, lon=34.80),
        place("park", types=("park",), lat=32.10, lon=34.82, rating=4.9),
    ]


def backends(found=None, claude=None, minutes=20):
    found = candidates() if found is None else found
    return {
        "nearby": lambda lat, lon, radius, types=None, *a, **k: found,
        "along": lambda polyline, query, *a, **k: found,
        "client": lambda: claude,
        "deps": {
            "travel_matrix": uniform_matrix(10),
            "direct_route": lambda *coordinates: {"minutes": minutes, "geometry": []},
            "route_through": lambda points: {"geometry": [list(p) for p in points], "steps": []},
            "agent_enabled": lambda: True,
            "budget_ok": lambda: True,
            "record_usage": lambda used: 0,
        },
    }


def agent_picks(place_id="coffee", minutes=40):
    return FakeClaude(
        reply(tool_use("t1", "search_places", **SEARCH_ARGS)),
        reply(
            tool_use(
                "t2", "submit_itinerary",
                stops=[{"place_id": place_id, "visit_minutes": minutes, "why": "nice"}], summary="Enjoy",
            )
        ),
    )


COFFEE = comparison.Scenario("quiet coffee", comparison.TEL_AVIV, comparison.JERUSALEM, 4, "coffee please", wants=comparison.COFFEE)


class SpendTests(unittest.TestCase):
    def test_cost_adds_places_searches_and_model_tokens(self):
        s = spend()
        s.searches = 2
        s.add_usage(usage(input_tokens=1_000_000, output_tokens=100_000, cache_read=500_000, cache_write=200_000))
        # searches 0.07 + input 2.00 + output 1.00 + cache read 0.10 + cache write 0.50
        self.assertAlmostEqual(s.usd, 0.07 + 2.0 + 1.0 + 0.1 + 0.5)

    def test_can_afford_looks_at_what_is_left(self):
        s = spend(cap=0.10)
        s.searches = 2  # 0.07 so far
        self.assertTrue(s.can_afford(0.03))
        self.assertFalse(s.can_afford(0.04))

    def test_since_reports_only_what_was_spent_after_the_snapshot(self):
        s = spend()
        s.searches = 1
        snapshot = s.snapshot()
        s.searches = 3
        s.add_usage(usage(input_tokens=1000, output_tokens=500))
        spent = s.since(snapshot)
        self.assertEqual(spent["places_searches"], 2)
        self.assertEqual(spent["tokens"], 1500)
        self.assertAlmostEqual(spent["total_usd"], 2 * 0.035 + 1000 * 2 / 1e6 + 500 * 10 / 1e6, places=4)

    def test_a_missing_usage_adds_nothing(self):
        s = spend()
        s.add_usage(None)
        self.assertEqual(s.usd, 0)

    def test_prices_come_from_the_settings_when_all_four_are_set(self):
        env = {
            "ANTHROPIC_PRICE_INPUT_PER_MTOK": "1",
            "ANTHROPIC_PRICE_OUTPUT_PER_MTOK": "5",
            "ANTHROPIC_PRICE_CACHE_READ_PER_MTOK": "0.1",
            "ANTHROPIC_PRICE_CACHE_WRITE_PER_MTOK": "1.5",
        }
        with mock.patch.dict(os.environ, env):
            prices, assumed = comparison.prices_from_settings()
        self.assertFalse(assumed)
        self.assertEqual(prices["output_tokens"], 5.0)

    def test_assumed_prices_are_used_and_flagged_when_any_is_missing(self):
        with mock.patch.dict(os.environ):
            for name in comparison.PRICE_SETTINGS.values():
                os.environ.pop(name, None)
            os.environ["ANTHROPIC_PRICE_INPUT_PER_MTOK"] = "1"
            prices, assumed = comparison.prices_from_settings()
        self.assertTrue(assumed)
        self.assertEqual(prices, comparison.ASSUMED_PRICES)


class GuardTests(unittest.TestCase):
    def test_the_client_passes_calls_through_and_counts_their_tokens(self):
        s = spend()
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH_ARGS), input_tokens=300, output_tokens=40))
        client = comparison.BudgetedClient(claude, s)
        client.messages.create(model="m", messages=[])
        self.assertEqual(len(claude.calls), 1)
        self.assertEqual(s.usage["input_tokens"], 300)
        self.assertEqual(s.usage["output_tokens"], 40)

    def test_the_client_refuses_a_call_the_cap_cannot_cover(self):
        s = spend(cap=0.04)  # less than the reserve for one model call
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH_ARGS)))
        client = comparison.BudgetedClient(claude, s)
        with self.assertRaises(comparison.BudgetExceeded):
            client.messages.create(model="m", messages=[])
        self.assertEqual(claude.calls, [])

    def test_the_agent_treats_a_refused_call_as_an_unavailable_model(self):
        client = comparison.BudgetedClient(FakeClaude(), spend(cap=0.01))
        outcome = agent.run_agent(client, make_box(), "trip")
        self.assertEqual((outcome.status, outcome.reason), ("failed", "llm_unavailable"))

    def test_searches_are_counted_and_every_place_is_remembered(self):
        s = spend()
        recorder = comparison.PlaceRecorder(s, lambda *a, **k: candidates(), lambda *a, **k: candidates()[:1])
        recorder.nearby(32.0, 34.7, 3000)
        recorder.along("poly", "park")
        self.assertEqual(s.searches, 2)
        self.assertEqual(set(recorder.places), {"coffee", "park"})

    def test_a_search_the_cap_cannot_cover_is_not_made(self):
        s = spend(cap=0.03)
        calls = []
        recorder = comparison.PlaceRecorder(s, lambda *a, **k: calls.append(1) or [], lambda *a, **k: [])
        with self.assertRaises(places.PlacesError):
            recorder.nearby(32.0, 34.7, 3000)
        self.assertEqual((calls, s.searches), ([], 0))

    def test_a_failed_search_is_not_counted(self):
        def failing(*args, **kwargs):
            raise places.PlacesError("down", transient=True)

        s = spend()
        recorder = comparison.PlaceRecorder(s, failing, failing)
        with self.assertRaises(places.PlacesError):
            recorder.nearby(32.0, 34.7, 3000)
        self.assertEqual(s.searches, 0)


class MeasureTests(unittest.TestCase):
    def result(self, stops, arrive_minutes=100):
        arrival = NOW + timedelta(minutes=arrive_minutes)
        return {
            "budget": {"buffer_minutes": 15, "drive_minutes": 20},
            "stops": stops,
            "arrive_destination": arrival.isoformat(),
            "final_drive_minutes": 10,
        }

    def stop(self, place_id, primary="park", rating=4.5, drive=10, visit=30, at=40):
        return {
            "id": place_id, "name": place_id.upper(), "primary_type": primary, "rating": rating, "rating_count": 100,
            "drive_minutes": drive, "visit_minutes": visit, "arrive": (NOW + timedelta(minutes=at)).isoformat(),
            "lat": 32.1, "lon": 34.8,
        }

    def test_measures_slack_extra_driving_and_rating(self):
        result = self.result([self.stop("a", rating=4.0), self.stop("b", rating=5.0, at=80)], arrive_minutes=100)
        measured = comparison.measure(COFFEE, result, NOW + timedelta(minutes=140), {})
        self.assertEqual(measured["slack_minutes"], 40)
        self.assertEqual(measured["extra_drive_minutes"], 10 + 10 + 10 - 20)
        self.assertEqual(measured["avg_rating"], 4.5)
        self.assertEqual(measured["visit_minutes"], 60)
        self.assertEqual(measured["stop_count"], 2)

    def test_the_preference_matches_on_any_type_of_the_place_not_only_the_main_one(self):
        result = self.result([self.stop("a", primary="food")])
        by_id = {"a": {"types": ["food", "bakery"]}}
        self.assertTrue(comparison.measure(COFFEE, result, NOW + timedelta(hours=4), by_id)["matches_preference"])
        self.assertFalse(comparison.measure(COFFEE, result, NOW + timedelta(hours=4), {})["matches_preference"])

    def test_no_preference_to_match_gives_none(self):
        plain = comparison.Scenario("plain", comparison.TEL_AVIV, comparison.JERUSALEM, 4)
        result = self.result([self.stop("a")])
        self.assertIsNone(comparison.measure(plain, result, NOW + timedelta(hours=4), {})["matches_preference"])

    def test_no_stops_means_no_match_and_a_problem(self):
        measured = comparison.measure(COFFEE, {"stops": [], "reason": "no_candidates"}, NOW + timedelta(hours=4), {})
        self.assertFalse(measured["matches_preference"])
        self.assertIn("no stops", measured["problems"][0])
        self.assertNotIn("slack_minutes", measured)

    def test_the_checks_catch_a_late_plan_and_too_many_stops(self):
        late = self.result([self.stop("a")], arrive_minutes=130)
        problems = comparison.check(COFFEE, late, NOW + timedelta(minutes=140))  # latest allowed: 125
        self.assertIn("arrives after the deadline less the safety margin", problems)
        many = self.result([self.stop(f"s{i}", at=40 + i) for i in range(4)])
        self.assertTrue(any("4 stops" in p for p in comparison.check(COFFEE, many, NOW + timedelta(hours=4))))


class RunScenarioTests(unittest.TestCase):
    def test_both_planners_see_the_same_places_and_the_planner_costs_no_search(self):
        s = spend()
        entry = comparison.run_scenario(COFFEE, s, NOW, backends(claude=agent_picks()))
        self.assertNotIn("error", entry)
        self.assertEqual(entry["agent"]["source"], "agent")
        self.assertEqual(entry["agent"]["stops"][0]["name"], "COFFEE")
        self.assertTrue(entry["agent"]["matches_preference"])
        self.assertIsNotNone(entry["planner"])
        self.assertEqual(entry["cost"]["places_searches"], 1)  # only the agent searched
        self.assertEqual(s.searches, 1)
        self.assertGreater(entry["cost"]["tokens"], 0)

    def test_the_planner_ignores_the_preference_and_takes_the_best_rated_place(self):
        entry = comparison.run_scenario(COFFEE, spend(), NOW, backends(claude=agent_picks()))
        planner_names = [stop["name"] for stop in entry["planner"]["stops"]]
        self.assertIn("PARK", planner_names)  # rating 4.9 beats the cafe
        self.assertTrue(entry["agent"]["matches_preference"])

    def test_spare_time_is_filled_the_same_way_for_both(self):
        entry = comparison.run_scenario(COFFEE, spend(), NOW, backends(claude=agent_picks(minutes=30)))
        self.assertGreater(entry["agent"]["stops"][0]["visit_minutes"], 30)
        for side in ("agent", "planner"):
            self.assertLessEqual(entry[side]["slack_minutes"], 240)

    def test_no_free_time_costs_nothing_and_has_nothing_to_compare(self):
        short = comparison.Scenario("too little time", comparison.TEL_AVIV, comparison.JERUSALEM, 1.05, expect_stops=False)
        s = spend()
        entry = comparison.run_scenario(short, s, NOW, backends(minutes=55))
        self.assertEqual(entry["agent"]["stop_count"], 0)
        self.assertEqual(entry["agent"]["problems"], [])
        self.assertIsNone(entry["planner"])
        self.assertEqual(s.usd, 0)

    def test_an_agent_failure_is_reported_and_the_planner_still_runs_on_what_was_found(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH_ARGS)), reply(stop="refusal"))
        entry = comparison.run_scenario(COFFEE, spend(), NOW, backends(claude=claude))
        self.assertEqual(entry["agent"]["status"], "degraded")
        self.assertEqual(entry["agent"]["source"], "baseline")
        self.assertEqual(entry["agent"]["degraded_reason"], "refused")
        self.assertIsNotNone(entry["planner"])

    def test_an_error_is_recorded_without_losing_the_cost_so_far(self):
        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        b = backends(claude=agent_picks())
        b["deps"]["direct_route"] = broken
        entry = comparison.run_scenario(COFFEE, spend(), NOW, b)
        self.assertIn("RuntimeError: boom", entry["error"])
        self.assertIn("cost", entry)


class RunComparisonTests(unittest.TestCase):
    def scenarios(self):
        short = comparison.Scenario("too little time", comparison.TEL_AVIV, comparison.JERUSALEM, 1.05, expect_stops=False)
        second = comparison.Scenario("museums", comparison.JERUSALEM, comparison.TEL_AVIV, 3, "museums", wants=comparison.MUSEUMS)
        return [COFFEE, second, short]

    def test_runs_every_scenario_when_the_budget_allows(self):
        calls = iter([agent_picks(), agent_picks()])
        b = backends()
        b["client"] = lambda: next(calls)
        report = comparison.run_comparison(self.scenarios(), max_usd=1.0, now=NOW, backends=b)
        self.assertEqual([r["scenario"] for r in report["results"]], ["quiet coffee", "museums", "too little time"])
        self.assertEqual(report["skipped"], [])
        self.assertLessEqual(report["spent_usd"], 1.0)
        self.assertGreater(report["spent_usd"], 0)

    def test_a_scenario_is_skipped_when_too_little_is_left_but_a_free_one_still_runs(self):
        report = comparison.run_comparison(self.scenarios(), max_usd=0.05, now=NOW, backends=backends(claude=agent_picks()))
        self.assertEqual([r["scenario"] for r in report["results"]], ["too little time"])
        self.assertEqual([item["scenario"] for item in report["skipped"]], ["quiet coffee", "museums"])
        self.assertEqual(report["spent_usd"], 0)

    def test_the_cap_is_never_passed_by_much(self):
        # Every scenario costs about 0.04 here; with a cap of 0.10 the third paid scenario is not started.
        many = [comparison.Scenario(f"s{i}", comparison.TEL_AVIV, comparison.JERUSALEM, 4, wants=comparison.COFFEE) for i in range(5)]
        pool = iter(agent_picks() for _ in range(5))
        b = backends()
        b["client"] = lambda: next(pool)
        report = comparison.run_comparison(many, max_usd=0.10, now=NOW, backends=b)
        self.assertLessEqual(report["spent_usd"], 0.10)
        self.assertTrue(report["skipped"])

    def test_only_filters_scenarios_by_name(self):
        report = comparison.run_comparison(self.scenarios(), max_usd=1.0, only="LITTLE", now=NOW, backends=backends())
        self.assertEqual([r["scenario"] for r in report["results"]], ["too little time"])

    def test_the_report_names_the_model_effort_and_price_basis(self):
        with mock.patch.dict(os.environ, {"AGENT_MODEL": "claude-haiku-5-5", "AGENT_EFFORT": "low"}):
            report = comparison.run_comparison(self.scenarios()[2:], max_usd=0.30, now=NOW, backends=backends())
        self.assertEqual((report["model"], report["effort"]), ("claude-haiku-5-5", "low"))
        self.assertEqual(report["max_usd"], 0.30)
        self.assertIn("generated", report)

    def test_progress_is_reported(self):
        seen = []
        comparison.run_comparison(self.scenarios()[2:], now=NOW, backends=backends(), progress=seen.append)
        self.assertEqual(seen, ["Running 'too little time' (1 of 1)"])

    def test_the_summary_counts_matches_for_each_side(self):
        pool = iter([agent_picks(), agent_picks()])
        b = backends()
        b["client"] = lambda: next(pool)
        report = comparison.run_comparison(self.scenarios()[:2], max_usd=1.0, now=NOW, backends=b)
        summary = report["summary"]
        self.assertEqual(summary["compared"], 2)
        self.assertEqual(summary["with_preference"], 2)
        # The agent picks the cafe, which satisfies the coffee scenario; the other asks for museums and there are none.
        self.assertEqual(summary["agent_matched"], 1)
        self.assertLessEqual(summary["planner_matched"], summary["with_preference"])


class MarkdownTests(unittest.TestCase):
    def report(self, **overrides):
        pool = iter([agent_picks(), agent_picks()])
        b = backends()
        b["client"] = lambda: next(pool)
        scenarios = [COFFEE, comparison.Scenario("too little time", comparison.TEL_AVIV, comparison.JERUSALEM, 1.05, expect_stops=False)]
        report = comparison.run_comparison(scenarios, max_usd=1.0, now=NOW, backends=b)
        report.update(overrides)
        return report

    def test_has_the_sections_a_reader_needs(self):
        text = comparison.render_markdown(self.report())
        for heading in ("# Leeway: AI agent vs rule-based planner", "## Summary", "## Cost", "## Scenarios", "### quiet coffee"):
            self.assertIn(heading, text)
        self.assertIn("same places", text)
        self.assertIn("Matched the stated preference", text)

    def test_says_when_prices_are_assumed(self):
        self.assertIn("assumed list prices", comparison.render_markdown(self.report(prices_assumed=True)))
        self.assertIn("from ANTHROPIC_PRICE_", comparison.render_markdown(self.report(prices_assumed=False)))

    def test_lists_skipped_scenarios_and_errors(self):
        report = self.report(skipped=[{"scenario": "museums", "reason": "not enough of the budget is left"}])
        report["results"].append({"scenario": "broken", "preferences": "", "hours": 1, "error": "RuntimeError: boom", "cost": report["results"][0]["cost"]})
        text = comparison.render_markdown(report)
        self.assertIn("Skipped 'museums'", text)
        self.assertIn("Failed: `RuntimeError: boom`", text)

    def test_explains_a_fallback(self):
        report = self.report()
        report["results"][0]["agent"].update({"source": "baseline", "degraded_reason": "refused", "status": "degraded"})
        self.assertIn("the agent did not finish: `refused`", comparison.render_markdown(report))

    def test_a_trip_with_no_free_time_is_not_called_a_fallback(self):
        text = comparison.render_markdown(self.report())
        self.assertNotIn("did not finish: `succeeded`", text)
        self.assertNotIn("did not finish", text)

    def test_the_summary_does_not_count_the_trip_without_free_time_as_an_agent_run(self):
        summary = self.report()["summary"]
        self.assertEqual(summary["agent_answered"], 1)
        self.assertEqual(summary["agent_fell_back"], 0)
        self.assertEqual(summary["scenarios_run"], 2)

    def test_is_valid_for_an_empty_run(self):
        empty = comparison.run_comparison([], now=NOW, backends=backends())
        self.assertIn("Scenarios run: 0", comparison.render_markdown(empty))


if __name__ == "__main__":
    unittest.main()
