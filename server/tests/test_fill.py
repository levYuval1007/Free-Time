import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fill
import planning
from test_agent import NOW, place
from test_agent_loop import SEARCH, FakeClaude, reply, submit, tool_use
from test_planning import deps, request

# NOW is Sunday 12:00 in Israel (UTC+3, so 180 minutes ahead of UTC).
CLOSES_AT_13 = [{"open": {"day": 0, "hour": 9, "minute": 0}, "close": {"day": 0, "hour": 13, "minute": 0}}]


def make_plan(visits, kinds=None, drive=10, final_drive=10, extra=None, periods=None):
    """A plan with the given visit lengths, ten minutes of driving between points, and times that fit together."""
    clock = NOW
    stops = []
    for index, visit in enumerate(visits):
        kind = (kinds or ["park"] * len(visits))[index]
        found = place(f"p{index}", types=(kind,), **({"periods": periods} if periods else {}))
        found["name"] = f"P{index}"
        arrive = clock + timedelta(minutes=drive)
        leave = arrive + timedelta(minutes=visit)
        stops.append({"place": found, "drive_minutes": drive, "arrive": arrive, "leave": leave, "visit_minutes": visit, **(extra or {})})
        clock = leave
    return {"stops": stops, "final_drive_minutes": final_drive, "arrive_destination": clock + timedelta(minutes=final_drive)}


def slack(plan, arrive_by):
    return (arrive_by - plan["arrive_destination"]).total_seconds() / 60


def fill_plan(plan, minutes_until_deadline, buffer=15):
    arrive_by = NOW + timedelta(minutes=minutes_until_deadline)
    filled, extensions = fill.fill_free_time(plan, NOW, arrive_by, buffer)
    return filled, extensions, arrive_by


class FillTests(unittest.TestCase):
    def test_a_plan_with_little_slack_is_left_alone(self):
        plan = make_plan([30, 30])  # arrives after 90 minutes
        filled, extensions, _ = fill_plan(plan, 90 + 40)
        self.assertIs(filled, plan)
        self.assertEqual(extensions, [])

    def test_slack_just_over_the_limit_is_filled_down_to_the_target(self):
        plan = make_plan([30, 30])
        filled, extensions, arrive_by = fill_plan(plan, 90 + 41)
        self.assertEqual(slack(filled, arrive_by), fill.TARGET_SLACK_MINUTES)
        self.assertEqual(sum(growth[2] - growth[1] for growth in extensions), 11)

    def test_a_lot_of_slack_is_shared_between_the_stops(self):
        plan = make_plan([30, 30], kinds=["park", "museum"])  # arrives after 90 minutes
        filled, extensions, arrive_by = fill_plan(plan, 90 + 110)
        self.assertEqual(slack(filled, arrive_by), 30)
        self.assertEqual([stop["visit_minutes"] for stop in filled["stops"]], [65, 75])  # the park stops at 65 (1.5 * 45, in steps of 5); the museum takes the rest

    def test_growth_stops_at_one_and_a_half_times_the_typical_visit(self):
        plan = make_plan([30])  # a park: typical visit 45, so at most 67, in steps of 5: 65
        filled, extensions, arrive_by = fill_plan(plan, 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], 65)
        self.assertEqual(extensions, [("P0", 30, 65)])
        self.assertGreater(slack(filled, arrive_by), fill.MAX_SLACK_MINUTES)  # nothing more can be done

    def test_a_museum_may_grow_more_than_a_park(self):
        filled, _, _ = fill_plan(make_plan([30], kinds=["museum"]), 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], 135)  # 1.5 * 90

    def test_a_longer_visit_than_the_cap_is_never_shortened(self):
        filled, extensions, _ = fill_plan(make_plan([150]), 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], 150)
        self.assertEqual(extensions, [])

    def test_times_of_later_stops_follow_the_longer_visit_and_drives_do_not_change(self):
        plan = make_plan([30, 30], kinds=["park", "museum"])
        filled, _, _ = fill_plan(plan, 90 + 110)
        first, second = filled["stops"]
        self.assertEqual(second["arrive"], first["leave"] + timedelta(minutes=10))
        self.assertEqual([s["drive_minutes"] for s in filled["stops"]], [10, 10])
        self.assertEqual(filled["final_drive_minutes"], 10)
        self.assertEqual(filled["arrive_destination"], second["leave"] + timedelta(minutes=10))

    def test_it_never_arrives_after_the_latest_allowed_time(self):
        for deadline in (130, 160, 220, 400):
            filled, _, arrive_by = fill_plan(make_plan([30, 30]), deadline, buffer=15)
            self.assertLessEqual(filled["arrive_destination"], arrive_by - timedelta(minutes=15))

    def test_a_large_safety_margin_is_respected(self):
        filled, _, arrive_by = fill_plan(make_plan([30]), 300, buffer=60)
        self.assertGreaterEqual(slack(filled, arrive_by), 60)

    def test_opening_hours_limit_the_growth(self):
        # Opens until 13:00 local time, arrival 12:10: the visit plus the 15 minute margin must end by 13:00.
        plan = make_plan([30], periods=CLOSES_AT_13)
        filled, extensions, _ = fill_plan(plan, 600)
        self.assertEqual(filled["stops"][0]["visit_minutes"], 35)
        self.assertEqual(extensions, [("P0", 30, 35)])

    def test_a_stop_with_unknown_hours_is_not_stretched(self):
        plan = make_plan([30])
        plan["stops"][0]["place"]["periods"] = None
        filled, extensions, _ = fill_plan(plan, 600)
        self.assertIs(filled, plan)
        self.assertEqual(extensions, [])

    def test_a_stop_that_cannot_grow_does_not_block_the_others(self):
        plan = make_plan([30, 30], kinds=["park", "park"])
        plan["stops"][0]["place"]["periods"] = CLOSES_AT_13
        filled, _, _ = fill_plan(plan, 90 + 110)
        first, second = filled["stops"]
        self.assertEqual(first["visit_minutes"], 35)
        self.assertGreater(second["visit_minutes"], 35)

    def test_extra_fields_survive(self):
        plan = make_plan([30], extra={"why": "A calm park"})
        plan["summary"] = "Easy walk"
        filled, _, _ = fill_plan(plan, 300)
        self.assertEqual(filled["stops"][0]["why"], "A calm park")
        self.assertEqual(filled["summary"], "Easy walk")

    def test_the_original_plan_is_not_modified(self):
        plan = make_plan([30])
        before = plan["stops"][0]["visit_minutes"], plan["arrive_destination"]
        fill_plan(plan, 300)
        self.assertEqual((plan["stops"][0]["visit_minutes"], plan["arrive_destination"]), before)

    def test_a_plan_without_stops_is_returned_as_it_is(self):
        plan = {"stops": [], "final_drive_minutes": 20, "arrive_destination": NOW + timedelta(minutes=20)}
        filled, extensions, _ = fill_plan(plan, 600)
        self.assertIs(filled, plan)
        self.assertEqual(extensions, [])


class FillInPlansTests(unittest.TestCase):
    def test_an_agent_plan_with_lots_of_spare_time_gets_longer_visits(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        with self.assertLogs("planning", level="INFO") as logged:
            outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(claude))
        stop = outcome.result["stops"][0]
        self.assertEqual(stop["visit_minutes"], 65)  # asked for 40; a park may reach 1.5 times its typical 45, in steps of 5
        self.assertEqual(stop["why"], "nice")
        self.assertEqual(outcome.result["summary"], "Enjoy")
        arrive = NOW + timedelta(minutes=10 + 65 + 10)
        self.assertEqual(outcome.result["arrive_destination"], arrive.isoformat())
        self.assertIn("lengthened visits", "\n".join(logged.output))

    def test_the_basic_planner_gets_the_same_treatment(self):
        outcome = planning.execute_plan(request(), lambda text: None, NOW, deps(enabled=False))
        self.assertEqual(outcome.result["source"], "baseline")
        for stop in outcome.result["stops"]:
            self.assertGreater(stop["visit_minutes"], 45)

    def test_a_plan_that_already_fits_is_not_touched(self):
        tight = request(deadline=NOW + timedelta(minutes=10 + 40 + 10 + 15 + 20))  # 20 minutes spare beyond the margin
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        outcome = planning.execute_plan(tight, lambda text: None, NOW, deps(claude))
        self.assertEqual(outcome.result["stops"][0]["visit_minutes"], 40)


if __name__ == "__main__":
    unittest.main()
