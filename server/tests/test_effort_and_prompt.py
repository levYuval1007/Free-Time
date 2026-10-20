import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent_tools
from test_agent import FakeSearch, context, place, uniform_matrix
from test_agent_loop import SEARCH, FakeClaude, make_box, reply, submit, tool_use

SEARCH_ARGS = {"lat": 32.08, "lon": 34.78, "radius_m": 2000}


def run_with_env(**env):
    """Run one agent round trip with the given environment and return the requests sent to the model."""
    claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
    with mock.patch.dict(os.environ, env, clear=False):
        if "AGENT_EFFORT" not in env:
            os.environ.pop("AGENT_EFFORT", None)
        agent.run_agent(claude, make_box(), "trip")
    return claude.calls


class EffortTests(unittest.TestCase):
    def test_nothing_is_sent_when_the_setting_is_absent(self):
        for call in run_with_env():
            self.assertNotIn("output_config", call)

    def test_the_level_is_sent_on_every_round(self):
        calls = run_with_env(AGENT_EFFORT="medium")
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call["output_config"], {"effort": "medium"})

    def test_case_and_spaces_do_not_matter(self):
        for call in run_with_env(AGENT_EFFORT="  Low "):
            self.assertEqual(call["output_config"], {"effort": "low"})

    def test_an_unknown_level_is_ignored_with_a_warning(self):
        with self.assertLogs("agent", level="WARNING") as logged:
            calls = run_with_env(AGENT_EFFORT="turbo")
        for call in calls:
            self.assertNotIn("output_config", call)
        self.assertIn("AGENT_EFFORT", "\n".join(logged.output))

    def test_the_status_line_shows_the_level(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        with mock.patch.dict(os.environ, {"AGENT_EFFORT": "medium"}):
            with self.assertLogs("agent", level="INFO") as logged:
                agent.run_agent(claude, make_box(), "trip")
        self.assertIn("effort=medium", "\n".join(logged.output))

    def test_the_default_is_named_in_the_status_line(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        with mock.patch.dict(os.environ):
            os.environ.pop("AGENT_EFFORT", None)
            with self.assertLogs("agent", level="INFO") as logged:
                agent.run_agent(claude, make_box(), "trip")
        self.assertIn("effort=default", "\n".join(logged.output))


class TravelTimeToolRemovedTests(unittest.TestCase):
    def test_the_model_is_not_offered_the_tool(self):
        self.assertNotIn("get_travel_time", [tool["name"] for tool in agent_tools.TOOLS])

    def test_calling_it_anyway_is_an_error(self):
        box = agent_tools.ToolBox(context([]), FakeSearch([]), uniform_matrix(10))
        text, is_error = box.run("get_travel_time", {"nodes": ["origin", "destination"]})
        self.assertTrue(is_error)
        self.assertIn("Unknown tool", text)


class SearchResultTimingTests(unittest.TestCase):
    def test_each_place_shows_all_three_drive_numbers(self):
        def matrix(points):
            # origin -> place 8 minutes, place -> destination 12, direct 10
            size = len(points)
            grid = [[5 for _ in range(size)] for _ in range(size)]
            for i in range(size):
                grid[i][i] = 0
            grid[0][1] = 10
            for i in range(2, size):
                grid[0][i] = 8
                grid[i][1] = 12
            return grid

        box = agent_tools.ToolBox(context([]), FakeSearch([place("a")]), matrix)
        found = json.loads(box.run("search_places", SEARCH_ARGS)[0])[0]
        self.assertEqual(found["minutes_from_start"], 8)
        self.assertEqual(found["minutes_to_destination"], 12)
        self.assertEqual(found["detour_minutes"], 10)  # 8 + 12 - 10


class PromptTests(unittest.TestCase):
    def test_the_prompt_explains_the_numbers_and_has_no_stale_tool(self):
        prompt = agent.SYSTEM_PROMPT
        self.assertIn("minutes_to_destination", prompt)
        self.assertIn("minutes_from_start", prompt)
        self.assertNotIn("get_travel_time", prompt)
        self.assertIn("Submit as soon as you have good options", prompt)

    def test_every_tool_the_prompt_names_exists(self):
        names = {tool["name"] for tool in agent_tools.TOOLS}
        for name in ("search_places", "search_along_route", "submit_itinerary"):
            self.assertIn(name, agent.SYSTEM_PROMPT)
            self.assertIn(name, names)

    def test_the_tool_descriptions_match_what_is_returned(self):
        for tool in agent_tools.TOOLS:
            if tool["name"].startswith("search"):
                self.assertIn("up to 12", tool["description"])
                self.assertIn("minutes_to_destination", tool["description"])
                self.assertNotIn("coordinates", tool["description"])


if __name__ == "__main__":
    unittest.main()
