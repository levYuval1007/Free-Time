import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from test_agent_loop import SEARCH, FakeClaude, make_box, reply, submit, tool_use


def run(**env):
    """One agent run with the given environment; returns the requests sent and the log lines."""
    claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
    with mock.patch.dict(os.environ, env):
        for name in ("AGENT_MODEL", "AGENT_EFFORT"):
            if name not in env:
                os.environ.pop(name, None)
        with assertLogs() as logged:
            agent.run_agent(claude, make_box(), "trip")
    return claude.calls, "\n".join(logged.output)


class assertLogs:
    """Collects the agent logger's output (warnings and info) for one run."""

    def __enter__(self):
        import logging

        self.handler = logging.Handler()
        self.records = []
        self.handler.emit = lambda record: self.records.append(record)
        self.logger = logging.getLogger("agent")
        self.previous = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self.handler)
        return self

    @property
    def output(self):
        return [f"{r.levelname}:{r.getMessage()}" for r in self.records]

    def __exit__(self, *exc):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous)
        return False


class ModelSettingTests(unittest.TestCase):
    def test_the_default_model_is_used_when_nothing_is_set(self):
        calls, _ = run()
        self.assertEqual({call["model"] for call in calls}, {"claude-sonnet-5"})

    def test_agent_model_is_sent_on_every_round(self):
        calls, _ = run(AGENT_MODEL="claude-haiku-5-5")
        self.assertEqual(len(calls), 2)
        self.assertEqual({call["model"] for call in calls}, {"claude-haiku-5-5"})

    def test_spaces_around_the_name_are_ignored(self):
        calls, _ = run(AGENT_MODEL="  claude-sonnet-5-5 ")
        self.assertEqual({call["model"] for call in calls}, {"claude-sonnet-5-5"})

    def test_a_value_that_is_not_a_claude_model_id_is_ignored_with_a_warning(self):
        for bad in ("gpt-4", "claude sonnet", "Claude-Sonnet-5", "claude-", "claude-../x", "x" * 5):
            calls, output = run(AGENT_MODEL=bad)
            self.assertEqual({call["model"] for call in calls}, {"claude-sonnet-5"}, bad)
            self.assertIn("AGENT_MODEL", output)

    def test_an_empty_value_means_the_default(self):
        calls, output = run(AGENT_MODEL="   ")
        self.assertEqual({call["model"] for call in calls}, {"claude-sonnet-5"})
        self.assertNotIn("AGENT_MODEL", output)

    def test_an_explicit_argument_wins_over_the_setting(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        with mock.patch.dict(os.environ, {"AGENT_MODEL": "claude-haiku-5-5"}):
            agent.run_agent(claude, make_box(), "trip", model="claude-opus-5")
        self.assertEqual({call["model"] for call in claude.calls}, {"claude-opus-5"})

    def test_the_model_and_effort_are_both_applied_and_logged(self):
        calls, output = run(AGENT_MODEL="claude-haiku-5-5", AGENT_EFFORT="low")
        for call in calls:
            self.assertEqual(call["model"], "claude-haiku-5-5")
            self.assertEqual(call["output_config"], {"effort": "low"})
        self.assertIn("model=claude-haiku-5-5 effort=low", output)

    def test_the_default_model_is_named_in_the_status_line(self):
        _, output = run()
        self.assertIn("model=claude-sonnet-5 effort=default", output)


if __name__ == "__main__":
    unittest.main()
