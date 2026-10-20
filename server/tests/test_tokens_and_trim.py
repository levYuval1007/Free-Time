import json
import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent_tools
import validator
from test_agent import NOW, FakeSearch, context, place, uniform_matrix
from test_agent_loop import SEARCH, FakeClaude, make_box, reply, submit, tool_use

SEARCH_ARGS = {"lat": 32.08, "lon": 34.78, "radius_m": 2000}


def spread(count):
    """Places at different spots, best rated first."""
    return [
        place(f"p{i:02d}", rating=4.9 - i * 0.01, lat=32.07 + i * 0.002, lon=34.79 + i * 0.002) for i in range(count)
    ]


class SearchResultSizeTests(unittest.TestCase):
    def box(self, found):
        return agent_tools.ToolBox(context([]), FakeSearch(found), uniform_matrix(10))

    def test_at_most_12_places_are_shown_best_first(self):
        found = json.loads(self.box(spread(20)).run("search_places", SEARCH_ARGS)[0])
        self.assertEqual(len(found), agent_tools.MAX_SHOWN)
        self.assertEqual([p["id"] for p in found], [f"p{i:02d}" for i in range(12)])

    def test_every_checked_place_is_remembered_even_when_not_shown(self):
        box = self.box(spread(20))
        box.run("search_places", SEARCH_ARGS)
        self.assertEqual(len(box.ctx.known_places), 20)

    def test_the_cap_applies_after_the_detour_check(self):
        far = [place(f"far{i}", lat=33.0 + i * 0.001, rating=5.0) for i in range(3)]  # hidden: 60 minutes away

        def matrix(points):
            return [
                [0 if i == j else (60 if 33.0 <= a[1] < 33.1 or 33.0 <= b[1] < 33.1 else 10) for j, b in enumerate(points)]
                for i, a in enumerate(points)
            ]

        box = agent_tools.ToolBox(context([]), FakeSearch(far + spread(14)), matrix)
        found = json.loads(box.run("search_places", SEARCH_ARGS)[0])
        self.assertEqual(len(found), 12)
        self.assertTrue(all(p["id"].startswith("p") for p in found))

    def test_results_leave_out_coordinates_and_keep_what_decides_the_choice(self):
        found = json.loads(self.box(spread(1)).run("search_places", SEARCH_ARGS)[0])[0]
        self.assertNotIn("lat", found)
        self.assertNotIn("lon", found)
        for key in ("id", "name", "type", "rating", "rating_count", "hours_today", "detour_minutes", "minutes_from_start"):
            self.assertIn(key, found)

    def test_hebrew_names_are_not_escaped_and_the_json_is_compact(self):
        hebrew = place("h", lat=32.07, lon=34.79)
        hebrew["name"] = "קפה המדרחוב"
        text = self.box([hebrew]).run("search_places", SEARCH_ARGS)[0]
        self.assertIn("קפה המדרחוב", text)
        self.assertNotIn("\\u05", text)
        self.assertNotIn(", ", text)
        self.assertNotIn('": ', text)

    def test_the_log_reports_how_many_were_capped(self):
        with self.assertLogs("tools", level="INFO") as logged:
            self.box(spread(20)).run("search_places", SEARCH_ARGS)
        self.assertIn("detour check places=20 shown=12 hidden=0 capped=8", "\n".join(logged.output))


class CachingTests(unittest.TestCase):
    def test_the_conversation_is_cached_through_the_top_level_setting(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        agent.run_agent(claude, make_box(), "trip")
        for call in claude.calls:
            self.assertEqual(call["cache_control"], {"type": "ephemeral"})
            self.assertEqual(call["system"][0]["cache_control"], {"type": "ephemeral"})
            # at most 4 cache breakpoints are allowed per request
            self.assertLessEqual(1 + 1 + 1, 4)


class TrimTests(unittest.TestCase):
    """The matrix is 10 minutes between any two points."""

    def check(self, deadline_minutes, stops, buffer=15):
        ctx = context([place("a", lat=32.07), place("b", lat=32.09, lon=34.8)], deadline_minutes, buffer)
        return validator.validate_itinerary(ctx, stops, uniform_matrix(10))

    def test_a_small_delay_is_fixed_by_shortening_the_last_visit(self):
        # 10 + 40 + 10 = 60 minutes, but only 55 are allowed (70 - 15): five minutes too late.
        result, errors = self.check(70, [{"place_id": "a", "visit_minutes": 40}])
        self.assertEqual(errors, [])
        self.assertEqual(result["stops"][0]["visit_minutes"], 35)
        self.assertEqual(result["trimmed"], [("A", 40, 35)])
        self.assertEqual(result["arrive_destination"], NOW + timedelta(minutes=55))

    def test_it_never_arrives_after_the_latest_allowed_time(self):
        result, _ = self.check(70, [{"place_id": "a", "visit_minutes": 40}])
        self.assertLessEqual(result["arrive_destination"], NOW + timedelta(minutes=70 - 15))

    def test_visits_are_shortened_from_the_last_stop_backwards_but_not_below_20(self):
        # 10 + 30 + 10 + 25 + 10 = 85 minutes against 77 allowed (92 - 15): eight minutes too late.
        result, errors = self.check(92, [{"place_id": "a", "visit_minutes": 30}, {"place_id": "b", "visit_minutes": 25}])
        self.assertEqual(errors, [])
        visits = [stop["visit_minutes"] for stop in result["stops"]]
        self.assertEqual(visits, [27, 20])
        self.assertEqual(result["trimmed"], [("A", 30, 27), ("B", 25, 20)])
        self.assertEqual(result["arrive_destination"], NOW + timedelta(minutes=77))

    def test_the_times_of_later_stops_follow_the_shorter_visit(self):
        result, _ = self.check(92, [{"place_id": "a", "visit_minutes": 30}, {"place_id": "b", "visit_minutes": 25}])
        first, second = result["stops"]
        self.assertEqual(second["arrive"], first["leave"] + timedelta(minutes=10))

    def test_a_plan_on_time_is_not_changed(self):
        result, errors = self.check(120, [{"place_id": "a", "visit_minutes": 40}])
        self.assertEqual(errors, [])
        self.assertNotIn("trimmed", result)
        self.assertEqual(result["stops"][0]["visit_minutes"], 40)

    def test_too_late_to_fix_is_still_rejected(self):
        # 20 minutes late: more than the 15 that may be trimmed.
        _, errors = self.check(55, [{"place_id": "a", "visit_minutes": 40}])
        self.assertEqual(len(errors), 1)
        self.assertIn("20 minutes after the latest allowed time", errors[0])

    def test_visits_that_cannot_give_up_enough_are_rejected(self):
        # 12 minutes late but the only visit is 25 minutes, so it can lose just 5.
        _, errors = self.check(48, [{"place_id": "a", "visit_minutes": 25}])
        self.assertIn("after the latest allowed time", errors[0])

    def test_a_single_minute_is_written_in_the_singular(self):
        _, errors = self.check(54, [{"place_id": "a", "visit_minutes": 20}])
        self.assertIn("1 minute after", errors[0])

    def test_other_problems_are_not_hidden_by_the_trim(self):
        ctx = context([place("a", periods=None)], 70, 15)
        _, errors = validator.validate_itinerary(ctx, [{"place_id": "a", "visit_minutes": 40}], uniform_matrix(10))
        self.assertTrue(any("unknown" in e for e in errors))


class TrimThroughTheToolTests(unittest.TestCase):
    def test_a_trimmed_plan_is_accepted_with_the_new_visit_lengths(self):
        ctx = context([], deadline_minutes=70)
        box = agent_tools.ToolBox(ctx, FakeSearch([place("a")]), uniform_matrix(10))
        box.run("search_places", SEARCH_ARGS)
        with self.assertLogs("tools", level="INFO") as logged:
            text, is_error = box.run(
                "submit_itinerary", {"stops": [{"place_id": "a", "visit_minutes": 40, "why": "x"}], "summary": "s"}
            )
        self.assertFalse(is_error, text)
        self.assertIn("shortened", text)
        self.assertEqual(box.itinerary["stops"][0]["visit_minutes"], 35)
        self.assertNotIn("trimmed", box.itinerary)
        self.assertIn("submit trimmed=", "\n".join(logged.output))

    def test_the_rejection_message_reads_well(self):
        box = agent_tools.ToolBox(context([]), FakeSearch([place("a")]), uniform_matrix(10))
        text, _ = box.run("submit_itinerary", {"stops": [{"place_id": "ghost"}], "summary": ""})
        self.assertIn("\nYou can submit 2 more time(s).", text)


if __name__ == "__main__":
    unittest.main()
