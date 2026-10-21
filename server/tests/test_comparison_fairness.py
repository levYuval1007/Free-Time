import json
import os
import sys
import unittest
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent_tools
import comparison
import ors
import planner
import planning
import validator
from test_agent import NOW, FakeSearch, context, place, uniform_matrix
from test_agent_loop import FakeClaude, reply, submit, tool_use
from test_comparison import COFFEE, SEARCH_ARGS, agent_picks, backends, spend
from test_fill import fill_plan, make_plan

ORIGIN = comparison.TEL_AVIV[0]
DESTINATION = comparison.JERUSALEM[0]
QUIET_COFFEE = comparison.SCENARIOS[0]


def stop(place_id, primary, visit=30, at=40, drive=10):
    return {
        "id": place_id, "name": place_id.upper(), "primary_type": primary, "rating": 4.5, "rating_count": 100,
        "drive_minutes": drive, "visit_minutes": visit, "arrive": (NOW + timedelta(minutes=at)).isoformat(),
        "lat": 32.1, "lon": 34.8,
    }


def result(stops, arrive_minutes=120):
    return {
        "budget": {"buffer_minutes": 15, "drive_minutes": 20},
        "stops": stops,
        "arrive_destination": (NOW + timedelta(minutes=arrive_minutes)).isoformat(),
        "final_drive_minutes": 10,
    }


class PreferenceMetricTests(unittest.TestCase):
    ARRIVE_BY = NOW + timedelta(hours=4)

    def measure(self, stops, by_id=None):
        return comparison.measure(QUIET_COFFEE, result(stops), self.ARRIVE_BY, by_id or {})

    def test_quiet_coffee_fits_when_stops_are_cafes_and_gardens(self):
        measured = self.measure([stop("a", "coffee_shop"), stop("b", "garden")], {"a": {"types": ["cafe"]}, "b": {"types": ["park"]}})
        self.assertEqual((measured["matching_stops"], measured["avoided_stops"]), (1, 0))
        self.assertTrue(measured["matches_preference"])

    def test_a_restaurant_contradicts_quiet_even_next_to_a_cafe(self):
        measured = self.measure(
            [stop("a", "restaurant"), stop("b", "coffee_shop")], {"a": {"types": ["cafe"]}, "b": {"types": ["cafe"]}}
        )
        self.assertEqual((measured["matching_stops"], measured["avoided_stops"]), (2, 1))
        self.assertFalse(measured["matches_preference"])

    def test_the_contradiction_looks_only_at_the_main_type(self):
        measured = self.measure([stop("a", "coffee_shop")], {"a": {"types": ["cafe", "restaurant", "bar"]}})
        self.assertEqual(measured["avoided_stops"], 0)
        self.assertTrue(measured["matches_preference"])

    def test_no_stop_of_a_wanted_type_does_not_fit(self):
        measured = self.measure([stop("a", "garden")], {"a": {"types": ["park"]}})
        self.assertEqual(measured["matching_stops"], 0)
        self.assertFalse(measured["matches_preference"])

    def test_a_park_fits_a_trip_with_small_children(self):
        kids = comparison.SCENARIOS[1]
        self.assertIn("park", kids.wants)
        measured = comparison.measure(kids, result([stop("a", "park")]), self.ARRIVE_BY, {})
        self.assertTrue(measured["matches_preference"])

    def test_scenarios_without_a_preference_have_nothing_to_count(self):
        plain = comparison.Scenario("plain", ORIGIN, DESTINATION, 4)
        measured = comparison.measure(plain, result([stop("a", "park")]), self.ARRIVE_BY, {})
        self.assertEqual((measured["matching_stops"], measured["avoided_stops"], measured["matches_preference"]), (None, None, None))

    def test_a_scenario_that_only_forbids_things_fits_when_nothing_is_forbidden(self):
        only_avoids = comparison.Scenario("calm", ORIGIN, DESTINATION, 4, avoids=("bar",))
        self.assertTrue(comparison.measure(only_avoids, result([stop("a", "park")]), self.ARRIVE_BY, {})["matches_preference"])
        self.assertFalse(comparison.measure(only_avoids, result([stop("a", "bar")]), self.ARRIVE_BY, {})["matches_preference"])

    def test_the_quiet_scenario_is_set_up_to_contradict_restaurants(self):
        self.assertIn("restaurant", QUIET_COFFEE.avoids)
        self.assertIn("bar", QUIET_COFFEE.avoids)
        self.assertIn("coffee_shop", QUIET_COFFEE.wants)


def far_matrix(points):
    """Ten minutes between the origin and the destination, but 25 minutes each way to any place: a detour of 40."""
    grid = []
    for i, a in enumerate(points):
        row = []
        for j, b in enumerate(points):
            if i == j:
                row.append(0)
            elif {a, b} == {tuple(ORIGIN), tuple(DESTINATION)}:
                row.append(10)
            elif a in (tuple(ORIGIN), tuple(DESTINATION)) or b in (tuple(ORIGIN), tuple(DESTINATION)):
                row.append(25)
            else:
                row.append(5)
        grid.append(row)
    return grid


class SameRulesForBothTests(unittest.TestCase):
    def request(self):
        return planning.PlanRequest(origin=ORIGIN, destination=DESTINATION, arrive_by=NOW + timedelta(hours=4))

    def deps(self, matrix=None):
        return SimpleNamespace_deps(matrix or uniform_matrix(10))

    def recheck(self, plan, matrix=None, known=None):
        free_time = {"buffer_minutes": 15, "free_minutes": 150, "drive_minutes": 20, "status": "ok"}
        known = known if known is not None else {s["id"]: place(s["id"], lat=32.1 + i * 0.01, lon=34.8) for i, s in enumerate(plan["stops"])}
        return comparison.recheck(plan, self.request(), NOW, free_time, [], known, self.deps(matrix))

    def formatted(self, *ids):
        return result([stop(i, "park", visit=30, at=40 + 50 * n, drive=10) for n, i in enumerate(ids)], arrive_minutes=20 + 50 * len(ids) + 10)

    def test_a_plan_inside_the_rules_has_no_problems(self):
        self.assertEqual(self.recheck(self.formatted("a")), [])

    def test_a_stop_with_too_big_a_detour_is_reported(self):
        errors = self.recheck(self.formatted("a"), matrix=far_matrix)
        self.assertEqual(len(errors), 1)
        self.assertIn("adds about 40 minutes of driving", errors[0])

    def test_a_stop_that_is_closed_is_reported(self):
        known = {"a": place("a", periods=[{"open": {"day": 0, "hour": 9, "minute": 0}, "close": {"day": 0, "hour": 10, "minute": 0}}])}
        errors = self.recheck(self.formatted("a"), known=known)
        self.assertTrue(any("is not open for the whole visit" in e for e in errors))

    def test_no_stops_means_nothing_to_check(self):
        self.assertEqual(self.recheck({"stops": [], "reason": "no_candidates"}), [])

    def test_a_routing_failure_is_reported_instead_of_raised(self):
        def down(points):
            raise ors.RouteError("The routing service is not responding right now.")

        errors = self.recheck(self.formatted("a"), matrix=down)
        self.assertEqual(len(errors), 1)
        self.assertIn("could not be re-checked", errors[0])

    def test_the_planners_big_detour_shows_up_in_the_comparison(self):
        # The agent is shown no place (the detour is too big) and its submissions are rejected, so it gives up;
        # the planner has no detour rule and happily takes them.
        claude = FakeClaude(
            reply(tool_use("t1", "search_places", **SEARCH_ARGS)),
            *[reply(submit(f"s{i}", place_id="coffee")) for i in range(3)],
        )
        b = backends(claude=claude)
        b["deps"]["travel_matrix"] = far_matrix
        entry = comparison.run_scenario(COFFEE, spend(), NOW, b)
        self.assertNotIn("error", entry)
        self.assertEqual(entry["agent"]["status"], "degraded")
        planner_problems = entry["planner"]["problems"]
        self.assertTrue(any("adds about 40 minutes" in p for p in planner_problems), planner_problems)

    def test_both_sides_are_checked_by_the_same_function(self):
        with mock.patch.object(comparison, "recheck", wraps=comparison.recheck) as spy:
            entry = comparison.run_scenario(COFFEE, spend(), NOW, backends(claude=agent_picks()))
        self.assertNotIn("error", entry)
        self.assertEqual(spy.call_count, 2)  # the agent's plan and the planner's plan

    def test_a_trip_without_stops_is_not_re_checked(self):
        short = comparison.Scenario("too little time", ORIGIN, DESTINATION, 1.05, expect_stops=False)
        with mock.patch.object(comparison, "recheck") as spy:
            comparison.run_scenario(short, spend(), NOW, backends(minutes=55))
        spy.assert_not_called()


def SimpleNamespace_deps(matrix):
    import types

    return types.SimpleNamespace(travel_matrix=matrix)


class SummaryAndReportTests(unittest.TestCase):
    def report(self):
        pool = iter([agent_picks(), agent_picks()])
        b = backends()
        b["client"] = lambda: next(pool)
        second = comparison.Scenario("museums", ORIGIN, DESTINATION, 3, "museums", wants=comparison.MUSEUMS)
        return comparison.run_comparison([COFFEE, second], max_usd=1.0, now=NOW, backends=b)

    def test_the_summary_has_the_share_of_fitting_stops_and_the_contradictions(self):
        summary = self.report()["summary"]
        for key in ("agent_fit_share", "planner_fit_share", "agent_contradicting", "planner_contradicting"):
            self.assertIn(key, summary)
        self.assertGreaterEqual(summary["agent_fit_share"], 0)
        self.assertLessEqual(summary["agent_fit_share"], 100)

    def test_the_markdown_shows_the_new_rows_and_says_both_are_checked_alike(self):
        text = comparison.render_markdown(self.report())
        self.assertIn("Share of stops that fit the preference", text)
        self.assertIn("Stops that contradict the preference", text)
        self.assertIn("Stops that fit or contradict it", text)
        self.assertIn("checked by the same rules", text)
        self.assertIn("fit,", text)

    def test_the_old_headline_row_is_still_there(self):
        self.assertIn("Matched the stated preference", comparison.render_markdown(self.report()))


class VisitLengthTests(unittest.TestCase):
    def test_typical_visits_are_realistic_for_cafes_food_and_big_attractions(self):
        def typical(kind):
            return planner.visit_minutes(place("x", types=(kind,)))

        self.assertEqual([typical(k) for k in ("cafe", "coffee_shop", "bakery", "restaurant")], [30, 30, 20, 60])
        self.assertEqual([typical(k) for k in ("aquarium", "zoo", "amusement_park")], [90, 120, 150])
        self.assertEqual(typical("park"), 45)  # unchanged
        self.assertEqual(typical("playground"), planner.DEFAULT_VISIT_MINUTES)

    def test_the_model_is_shown_the_shorter_typical_visit_for_a_cafe(self):
        ctx = context([])
        box = agent_tools.ToolBox(ctx, FakeSearch([place("c", types=("coffee_shop",))]), uniform_matrix(10))
        found = json.loads(box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})[0])
        self.assertEqual(found[0]["typical_visit_minutes"], 30)

    def test_a_cafe_visit_is_never_stretched_beyond_three_quarters_of_an_hour(self):
        filled, _, _ = fill_plan(make_plan([20], kinds=["cafe"]), 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], 45)  # 1.5 * 30

    def test_a_bakery_stays_short(self):
        filled, _, _ = fill_plan(make_plan([20], kinds=["bakery"]), 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], 30)  # 1.5 * 20

    def test_big_attractions_may_take_longer(self):
        filled, _, _ = fill_plan(make_plan([30], kinds=["zoo"]), 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], validator.MAX_VISIT_MINUTES)

    def test_the_spare_time_is_spread_so_a_cafe_does_not_take_it_all(self):
        plan = make_plan([30, 30], kinds=["cafe", "museum"])  # arrives after 90 minutes
        filled, _, arrive_by = fill_plan(plan, 90 + 100)
        visits = [s["visit_minutes"] for s in filled["stops"]]
        self.assertLessEqual(visits[0], 60)
        self.assertGreater(visits[1], visits[0] - 1)


if __name__ == "__main__":
    unittest.main()
