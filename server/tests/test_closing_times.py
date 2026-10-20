import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent_tools
import hours
import validator
from test_agent import FakeSearch, NOW, context, place, uniform_matrix

ISRAEL = 180  # minutes ahead of UTC
# NOW is Sunday 12:00 local time (09:00 UTC).


def sunday(open_hour, close_hour):
    return [{"open": {"day": 0, "hour": open_hour, "minute": 0}, "close": {"day": 0, "hour": close_hour, "minute": 0}}]


class MinutesUntilChangeTests(unittest.TestCase):
    def test_open_now_gives_the_minutes_until_closing(self):
        self.assertEqual(hours.minutes_until_change(sunday(9, 17), ISRAEL, NOW), (True, 300))

    def test_closed_now_gives_the_minutes_until_opening(self):
        self.assertEqual(hours.minutes_until_change(sunday(14, 20), ISRAEL, NOW), (False, 120))

    def test_a_place_open_all_the_time_has_no_closing(self):
        always = [{"open": {"day": 0, "hour": 0, "minute": 0}}]
        self.assertEqual(hours.minutes_until_change(always, ISRAEL, NOW), (True, None))

    def test_unknown_hours_give_none(self):
        self.assertIsNone(hours.minutes_until_change(None, ISRAEL, NOW))
        self.assertIsNone(hours.minutes_until_change([], ISRAEL, NOW))
        self.assertIsNone(hours.minutes_until_change(sunday(9, 17), None, NOW))

    def test_opening_hours_that_cross_midnight(self):
        saturday_night = [{"open": {"day": 6, "hour": 22, "minute": 0}, "close": {"day": 0, "hour": 2, "minute": 0}}]
        saturday_2300_local = datetime(2026, 9, 19, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(hours.minutes_until_change(saturday_night, ISRAEL, saturday_2300_local), (True, 180))
        sunday_0100_local = datetime(2026, 9, 19, 22, 0, tzinfo=timezone.utc)
        self.assertEqual(hours.minutes_until_change(saturday_night, ISRAEL, sunday_0100_local), (True, 60))

    def test_closed_today_opens_on_another_day(self):
        monday = [{"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 17, "minute": 0}}]
        # Sunday 12:00 to Monday 09:00 is 21 hours
        self.assertEqual(hours.minutes_until_change(monday, ISRAEL, NOW), (False, 21 * 60))

    def test_exactly_at_closing_time_it_is_closed(self):
        open_, minutes = hours.minutes_until_change(sunday(9, 12), ISRAEL, NOW)
        self.assertFalse(open_)
        self.assertEqual(minutes, 7 * 24 * 60 - 180)  # next Sunday 09:00

    def test_the_local_time_zone_matters(self):
        # The same instant is 09:00 in UTC+0, when a place that opens at 09:00 is just opening.
        periods = sunday(9, 17)
        self.assertEqual(hours.minutes_until_change(periods, 0, NOW), (True, 480))
        self.assertEqual(hours.minutes_until_change(periods, ISRAEL, NOW), (True, 300))

    def test_seconds_do_not_change_the_answer(self):
        self.assertEqual(hours.minutes_until_change(sunday(9, 17), ISRAEL, NOW + timedelta(seconds=40)), (True, 300))


class SearchResultTests(unittest.TestCase):
    def results(self, *found):
        ctx = context([])
        box = agent_tools.ToolBox(ctx, FakeSearch(list(found)), uniform_matrix(10))
        text, is_error = box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        self.assertFalse(is_error, text)
        return {item["id"]: item for item in json.loads(text)}

    def test_an_open_place_shows_when_it_closes(self):
        found = self.results(place("a", periods=sunday(9, 13)))
        self.assertEqual(found["a"]["closes_in_minutes"], 60)
        self.assertNotIn("opens_in_minutes", found["a"])

    def test_a_closed_place_shows_when_it_opens(self):
        found = self.results(place("a", periods=sunday(14, 20)))
        self.assertEqual(found["a"]["opens_in_minutes"], 120)
        self.assertNotIn("closes_in_minutes", found["a"])

    def test_a_place_open_all_day_shows_neither(self):
        found = self.results(place("a"))
        self.assertNotIn("closes_in_minutes", found["a"])
        self.assertNotIn("opens_in_minutes", found["a"])

    def test_the_numbers_are_whole_minutes_from_the_start_of_the_plan(self):
        found = self.results(place("a", periods=sunday(9, 13)), place("b", periods=sunday(9, 17), lat=32.2, lon=34.9))
        self.assertEqual((found["a"]["closes_in_minutes"], found["b"]["closes_in_minutes"]), (60, 300))
        self.assertIsInstance(found["a"]["closes_in_minutes"], int)

    def test_the_model_is_told_how_to_use_them(self):
        for text in (agent.SYSTEM_PROMPT, *[t["description"] for t in agent_tools.TOOLS if t["name"].startswith("search")]):
            self.assertIn("closes_in_minutes", text)
            self.assertIn("opens_in_minutes", text)
        self.assertIn("at least 15 minutes before closing", agent.SYSTEM_PROMPT)


class RejectionMessageTests(unittest.TestCase):
    def reject(self, found):
        ctx = context([found], deadline_minutes=600)
        result, errors = validator.validate_itinerary(
            ctx, [{"place_id": found["id"], "visit_minutes": 60}], uniform_matrix(10)
        )
        self.assertIsNone(result)
        return errors

    def test_a_rejection_for_a_closed_place_says_when_it_is_open(self):
        errors = self.reject(place("a", periods=sunday(9, 13)))  # arrive 12:10, leave 13:10, closes 13:00
        self.assertEqual(len(errors), 1)
        self.assertIn("is not open for the whole visit (12:10-13:10 local time", errors[0])
        self.assertIn("its hours that day: Monday: 9-5", errors[0])

    def test_the_hours_are_those_of_the_day_of_the_visit(self):
        found = place("a", periods=sunday(9, 13))
        found["weekday_text"] = [f"Day {i}" for i in range(7)]  # Monday first, so Sunday is the last one
        self.assertIn("its hours that day: Day 6", self.reject(found)[0])

    def test_without_hours_text_the_message_is_unchanged(self):
        found = place("a", periods=sunday(9, 13))
        found["weekday_text"] = None
        errors = self.reject(found)
        self.assertNotIn("its hours", errors[0])
        self.assertIn("is not open for the whole visit", errors[0])

    def test_the_message_stays_one_line(self):
        self.assertNotIn("\n", self.reject(place("a", periods=sunday(9, 13)))[0])


if __name__ == "__main__":
    unittest.main()
