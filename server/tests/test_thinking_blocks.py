import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
from test_agent_loop import SEARCH, FakeClaude, make_box, reply, submit, text_block, tool_use


def thinking_block(signature="sig-1"):
    return SimpleNamespace(type="thinking", thinking="", signature=signature)


class ReplayTests(unittest.TestCase):
    def history_after_first_round(self, *first_round_blocks):
        claude = FakeClaude(reply(*first_round_blocks), reply(submit("t2")))
        agent.run_agent(claude, make_box(), "trip")
        return claude.calls[1]["messages"]

    def test_thinking_blocks_are_sent_back_unchanged_and_in_order(self):
        messages = self.history_after_first_round(
            thinking_block("sig-abc"), text_block("Looking"), tool_use("t1", "search_places", **SEARCH)
        )
        assistant = messages[1]["content"]
        self.assertEqual([block.type for block in assistant], ["thinking", "text", "tool_use"])
        self.assertEqual(assistant[0].signature, "sig-abc")
        self.assertEqual(assistant[0].thinking, "")

    def test_redacted_thinking_is_kept_too(self):
        redacted = SimpleNamespace(type="redacted_thinking", data="opaque")
        messages = self.history_after_first_round(redacted, tool_use("t1", "search_places", **SEARCH))
        self.assertEqual([block.type for block in messages[1]["content"]], ["redacted_thinking", "tool_use"])
        self.assertEqual(messages[1]["content"][0].data, "opaque")

    def test_the_tool_results_still_follow_in_one_user_message(self):
        messages = self.history_after_first_round(thinking_block(), tool_use("t1", "search_places", **SEARCH))
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertEqual(messages[2]["content"][0]["tool_use_id"], "t1")


class BlockLogTests(unittest.TestCase):
    def test_the_round_log_shows_which_kinds_of_blocks_came_back(self):
        claude = FakeClaude(
            reply(thinking_block(), text_block("Looking"), tool_use("t1", "search_places", **SEARCH)),
            reply(submit("t2")),
        )
        with self.assertLogs("agent", level="INFO") as logged:
            agent.run_agent(claude, make_box(), "trip")
        rounds = [line for line in logged.output if "round=" in line]
        self.assertIn("blocks=[thinking, text:7, tool_use]", rounds[0])
        self.assertIn("blocks=[tool_use]", rounds[1])

    def test_an_empty_reply_is_logged_as_none(self):
        with self.assertLogs("agent", level="INFO") as logged:
            agent.run_agent(FakeClaude(reply(stop="end_turn")), make_box(), "trip")
        self.assertIn("blocks=[none]", logged.output[0])

    def test_the_log_never_contains_the_text_itself(self):
        claude = FakeClaude(reply(text_block("secret reasoning words"), stop="end_turn"))
        with self.assertLogs("agent", level="INFO") as logged:
            agent.run_agent(claude, make_box(), "trip")
        self.assertNotIn("secret", "\n".join(logged.output))


if __name__ == "__main__":
    unittest.main()
