import json
import os
import sys
import unittest
from datetime import timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent_tools
import validator
from test_agent import NOW, ORIGIN, DESTINATION, FakeSearch, place, uniform_matrix
from test_agent_loop import FakeClaude, SEARCH, reply, submit, text_block, tool_use


def box_with(found, deadline_minutes=240):
    ctx = validator.TripContext(
        now=NOW, arrive_by=NOW + timedelta(minutes=deadline_minutes), buffer_minutes=15, origin=ORIGIN, destination=DESTINATION
    )
    box = agent_tools.ToolBox(ctx, FakeSearch(found), uniform_matrix(10))
    box.run("search_places", SEARCH)
    return box


def stops(*ids, visit=40):
    return {"stops": [{"place_id": i, "visit_minutes": visit, "why": "nice"} for i in ids], "summary": "Enjoy"}


def distinct(count):
    return [place(name, lat=32.07 + index * 0.01, lon=34.79 + index * 0.01) for index, name in enumerate("abcd"[:count])]


class ReconsiderTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(agent_tools, "RECONSIDER", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_much_unused_time_with_room_for_another_stop_asks_the_model_once_more(self):
        box = box_with(distinct(2))  # one short visit in a four hour window
        text, is_error = box.run("submit_itinerary", stops("a"))
        self.assertTrue(is_error)
        self.assertIn("arrive about", text)
        self.assertIn("only once", text)
        self.assertIsNone(box.itinerary)

    def test_asking_does_not_use_up_a_submission(self):
        box = box_with(distinct(2))
        box.run("submit_itinerary", stops("a"))
        self.assertEqual(box.submissions, 0)
        self.assertFalse(box.finished)

    def test_a_better_itinerary_is_accepted(self):
        box = box_with(distinct(2))
        box.run("submit_itinerary", stops("a"))
        text, is_error = box.run("submit_itinerary", stops("a", "b"))
        self.assertFalse(is_error)
        self.assertEqual(len(box.itinerary["stops"]), 2)

    def test_the_same_stops_again_are_accepted(self):
        box = box_with(distinct(2))
        box.run("submit_itinerary", stops("a"))
        text, is_error = box.run("submit_itinerary", stops("a"))
        self.assertFalse(is_error)
        self.assertEqual([s["place"]["id"] for s in box.itinerary["stops"]], ["a"])

    def test_it_is_not_asked_when_the_window_is_nearly_used(self):
        box = box_with(distinct(2), deadline_minutes=95)  # 10 + 40 + 10 plus a longer visit leaves little over
        text, is_error = box.run("submit_itinerary", stops("a"))
        self.assertFalse(is_error)

    def test_it_is_not_asked_when_there_is_nothing_else_to_add(self):
        box = box_with(distinct(1))
        text, is_error = box.run("submit_itinerary", stops("a"))
        self.assertFalse(is_error)

    def test_it_is_not_asked_when_three_stops_are_already_planned(self):
        box = box_with(distinct(4))
        text, is_error = box.run("submit_itinerary", stops("a", "b", "c", visit=20))
        self.assertFalse(is_error)

    def test_a_valid_plan_is_kept_if_the_better_try_is_rejected_until_submissions_run_out(self):
        box = box_with(distinct(2))
        box.run("submit_itinerary", stops("a"))
        for _ in range(agent_tools.MAX_SUBMISSIONS - 1):
            _, is_error = box.run("submit_itinerary", stops("missing"))
            self.assertTrue(is_error)
        text, is_error = box.run("submit_itinerary", stops("missing"))
        self.assertFalse(is_error)
        self.assertEqual([s["place"]["id"] for s in box.itinerary["stops"]], ["a"])

    def test_settle_uses_the_held_plan_when_the_model_stops_answering(self):
        box = box_with(distinct(2))
        box.run("submit_itinerary", stops("a"))
        box.settle()
        self.assertEqual([s["place"]["id"] for s in box.itinerary["stops"]], ["a"])
        self.assertEqual(box.itinerary["stops"][0]["why"], "nice")

    def test_settle_does_nothing_without_a_held_plan(self):
        box = box_with(distinct(2))
        box.settle()
        self.assertIsNone(box.itinerary)


class ReconsiderInTheLoopTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(agent_tools, "RECONSIDER", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_loop(self, *replies):
        box = box_with(distinct(2))
        claude = FakeClaude(*replies)
        outcome = agent.run_agent(claude, box, "trip")
        return outcome, claude

    def test_the_model_adds_a_stop_after_being_asked(self):
        outcome, claude = self.run_loop(
            reply(submit("s1", "a")),
            reply(tool_use("s2", "submit_itinerary", **stops("a", "b"))),
        )
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(len(outcome.itinerary["stops"]), 2)
        self.assertEqual(len(claude.calls), 2)

    def test_a_model_that_answers_with_text_keeps_its_first_valid_plan(self):
        outcome, _ = self.run_loop(reply(submit("s1", "a")), reply(text_block("I like it"), stop="end_turn"))
        self.assertEqual(outcome.status, "ok")
        self.assertEqual(len(outcome.itinerary["stops"]), 1)

    def test_the_request_is_in_the_tool_result_marked_as_an_error(self):
        _, claude = self.run_loop(reply(submit("s1", "a")), reply(submit("s2", "a")))
        results = claude.calls[1]["messages"][-1]["content"]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("valid", results[0]["content"])


if __name__ == "__main__":
    unittest.main()
