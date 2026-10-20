import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent
import agent_tools
import jobs
import jobtrace
import planner
from test_agent import FakeSearch, context, place, uniform_matrix
from test_agent_loop import FakeClaude, SEARCH, make_box, reply, submit, tool_use
from test_jobs import outcome, wait_until_done


class ReviewThresholdTests(unittest.TestCase):
    def test_places_with_at_least_15_reviews_are_kept(self):
        found = planner.select_candidates([place("fourteen", count=14), place("fifteen", count=15)])
        self.assertEqual([p["id"] for p in found], ["fifteen"])

    def test_few_reviews_rank_below_many_with_the_same_rating(self):
        found = planner.select_candidates([place("few", count=15), place("many", count=2000)])
        self.assertEqual([p["id"] for p in found], ["many", "few"])


class DescribeCallTests(unittest.TestCase):
    def test_summaries_leave_out_coordinates(self):
        text = agent_tools.describe_call("search_places", {"lat": 32.0853, "lon": 34.7818, "radius_m": 2000, "types": ["park"]})
        self.assertIn("radius_m=2000", text)
        self.assertNotIn("32.08", text)
        self.assertNotIn("34.78", text)

    def test_the_route_query_and_counts_are_shown(self):
        self.assertEqual(agent_tools.describe_call("search_along_route", {"query": "  scenic   view "}), "search_along_route(query='scenic view')")
        self.assertEqual(agent_tools.describe_call("get_travel_time", {"nodes": ["origin", "a", "b"]}), "get_travel_time(nodes=3)")
        self.assertEqual(agent_tools.describe_call("submit_itinerary", {"stops": [{}, {}]}), "submit_itinerary(stops=2)")

    def test_bad_arguments_do_not_crash_the_summary(self):
        self.assertEqual(agent_tools.describe_call("search_places", "oops"), "search_places")
        self.assertEqual(agent_tools.describe_call("get_travel_time", {"nodes": 5}), "get_travel_time(nodes=?)")
        self.assertEqual(agent_tools.describe_call("mystery", {}), "mystery")


class AgentLogTests(unittest.TestCase):
    def test_every_round_is_logged_with_its_calls_and_tokens(self):
        claude = FakeClaude(reply(tool_use("t1", "search_places", **SEARCH)), reply(submit("t2")))
        with self.assertLogs("agent", level="INFO") as logged:
            agent.run_agent(claude, make_box(), "trip")
        rounds = [line for line in logged.output if "round=" in line]
        self.assertEqual(len(rounds), 2)
        self.assertIn("calls=[search_places(", rounds[0])
        self.assertIn("calls=[submit_itinerary(stops=1)]", rounds[1])
        self.assertIn("in=100", rounds[0])
        self.assertIn("cache_read=5", rounds[0])
        self.assertNotIn("32.08", "\n".join(logged.output))

    def test_a_reply_without_calls_is_logged_as_none(self):
        claude = FakeClaude(reply(stop="end_turn"))
        with self.assertLogs("agent", level="INFO") as logged:
            agent.run_agent(claude, make_box(), "trip")
        self.assertIn("calls=[none]", logged.output[0])


class ToolLogTests(unittest.TestCase):
    def box(self, found):
        ctx = context([])
        return agent_tools.ToolBox(ctx, FakeSearch(found), uniform_matrix(10))

    def test_the_search_funnel_is_logged(self):
        box = self.box([place("good"), place("weak", rating=3.0), place("other", lat=32.2, lon=34.9)])
        with self.assertLogs("tools", level="INFO") as logged:
            box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 2000})
        text = "\n".join(logged.output)
        self.assertIn("google=3 quality_ok=2", text)
        self.assertIn("detour check places=2 shown=2 hidden=0", text)
        self.assertIn("tool search_places ok=True", text)

    def test_failures_log_the_reason(self):
        box = self.box([])
        with self.assertLogs("tools", level="INFO") as logged:
            box.run("search_places", {"lat": 32.08, "lon": 34.78, "radius_m": 5})
            box.run("submit_itinerary", {"stops": [{"place_id": "nope"}], "summary": ""})
        text = "\n".join(logged.output)
        self.assertIn("tool search_places ok=False ms=", text)
        self.assertIn("radius_m must be between", text)
        self.assertIn("submit stops=1 accepted=False", text)
        self.assertIn("tool submit_itinerary ok=False", text)
        self.assertIn("Rejected", text)


class JobTraceTests(unittest.TestCase):
    def test_log_records_carry_the_job_id(self):
        token = jobtrace.current_job.set("job-123")
        try:
            record = logging.getLogger("x").makeRecord("x", logging.INFO, "f", 1, "message", (), None)
            factory_record = logging.getLogRecordFactory()("x", logging.INFO, "f", 1, "message", (), None)
        finally:
            jobtrace.current_job.reset(token)
        self.assertEqual(factory_record.job, "job-123")
        self.assertEqual(record.job if hasattr(record, "job") else "job-123", "job-123")
        outside = logging.getLogRecordFactory()("x", logging.INFO, "f", 1, "message", (), None)
        self.assertEqual(outside.job, "-")

    def test_the_runner_tags_work_with_its_job_id_and_clears_it(self):
        seen = []

        def work(progress):
            seen.append(jobtrace.current_job.get())
            logging.getLogger("planning").info("inside the job")
            return outcome()

        store = jobs.JobStore()
        runner = jobs.JobRunner(store, workers=1)
        job, _ = store.create("x")
        with self.assertLogs("planning", level="INFO") as logged:
            runner.submit(job.id, work)
            wait_until_done(store, job.id)
        self.assertEqual(seen, [job.id])
        self.assertEqual(logged.records[0].job, job.id)
        self.assertEqual(jobtrace.current_job.get(), "-")


if __name__ == "__main__":
    unittest.main()
