import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import comparison
import evalservice
import reportstore


def minimal_report(**overrides):
    report = {
        "generated": "2026-10-20T10:00:00+00:00", "model": "claude-sonnet-5", "effort": "default", "max_usd": 0.3,
        "spent_usd": 0.0, "prices_assumed": True, "results": [], "skipped": [], "summary": comparison.summarize([]),
    }
    report.update(overrides)
    return report


def wait_for(runner, run_id, status, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        view = runner.view(run_id)
        if view and view["status"] == status:
            return view
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {status}: {runner.view(run_id)}")


class EvalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = reportstore.FileReportStore(Path(self.temp.name))

    def runner(self, run=None):
        return evalservice.EvalRunner(self.store, run or (lambda **kwargs: minimal_report()))

    def test_a_run_finishes_with_a_report_and_saved_files(self):
        runner = self.runner()
        run_id = runner.start(0.3)
        view = wait_for(runner, run_id, "done")
        self.assertEqual(view["report"]["model"], "claude-sonnet-5")
        self.assertEqual(len(view["files"]), 2)
        self.assertEqual(sorted(self.store.names()), [f"{run_id}.json", f"{run_id}.md"])
        self.assertIn("# Leeway: AI agent vs rule-based planner", self.store.read(f"{run_id}.md"))
        self.assertIn('"model": "claude-sonnet-5"', self.store.read(f"{run_id}.json"))

    def test_the_settings_reach_the_comparison_and_progress_is_visible(self):
        seen = {}
        release = threading.Event()

        def run(max_usd, only, progress):
            seen.update(max_usd=max_usd, only=only)
            progress("Running 'quiet coffee' (1 of 2)")
            release.wait(2)
            return minimal_report()

        runner = self.runner(run)
        run_id = runner.start(0.25, "coffee")
        for _ in range(200):
            if runner.view(run_id)["progress"].startswith("Running"):
                break
            time.sleep(0.01)
        self.assertEqual(runner.view(run_id)["progress"], "Running 'quiet coffee' (1 of 2)")
        self.assertEqual(runner.view(run_id)["status"], "running")
        release.set()
        wait_for(runner, run_id, "done")
        self.assertEqual(seen, {"max_usd": 0.25, "only": "coffee"})

    def test_only_one_comparison_runs_at_a_time(self):
        release = threading.Event()
        runner = self.runner(lambda **kwargs: release.wait(2) and minimal_report())
        first = runner.start(0.3)
        with self.assertRaises(evalservice.Busy):
            runner.start(0.3)
        release.set()
        wait_for(runner, first, "done")
        second = runner.start(0.3)  # free again
        wait_for(runner, second, "done")

    def test_the_report_is_written_to_the_log_line_by_line(self):
        runner = self.runner()
        with self.assertLogs("evals", level="INFO") as logged:
            wait_for(runner, runner.start(0.3), "done")
        lines = [line for line in logged.output if "report |" in line]
        self.assertTrue(any("# Leeway: AI agent vs rule-based planner" in line for line in lines))
        self.assertGreater(len(lines), 10)

    def test_a_crash_is_reported_without_leaking_its_message(self):
        def run(**kwargs):
            raise RuntimeError("secret detail sk-ant-123")

        runner = self.runner(run)
        with self.assertLogs("evals", level="ERROR"):
            view = wait_for(runner, runner.start(0.3), "failed")
        self.assertNotIn("secret", str(view))
        self.assertEqual(view["error"], "The comparison failed. See the server log.")
        self.assertIsNone(view["report"])
        runner._run = lambda **kwargs: minimal_report()
        wait_for(runner, runner.start(0.3), "done")  # a failed run does not block the next

    def test_a_disk_that_cannot_be_written_does_not_lose_the_report(self):
        class Broken:
            def save(self, name, text):
                raise OSError("read-only file system")

        runner = evalservice.EvalRunner(Broken(), lambda **kwargs: minimal_report())
        with self.assertLogs("evals", level="WARNING"):
            view = wait_for(runner, runner.start(0.3), "done")
        self.assertEqual(view["files"], [])
        self.assertIsNotNone(view["report"])
        self.assertIsNotNone(runner.markdown(view["id"]))

    def test_view_hides_the_markdown_and_unknown_ids_are_none(self):
        runner = self.runner()
        run_id = runner.start(0.3)
        view = wait_for(runner, run_id, "done")
        self.assertNotIn("markdown", view)
        self.assertIsNone(runner.view("eval-nope"))
        self.assertIsNone(runner.markdown("eval-nope"))
        self.assertNotIn("report", runner.view(run_id, with_report=False))

    def test_recent_lists_newest_first_and_old_runs_leave_memory_but_stay_readable(self):
        runner = self.runner()
        ids = []
        for _ in range(evalservice.KEEP_RUNS + 2):
            run_id = runner.start(0.3)
            wait_for(runner, run_id, "done")
            ids.append(run_id)
        recent = runner.recent()
        self.assertEqual(recent[0]["id"], ids[-1])
        self.assertEqual(sorted(run["id"] for run in recent), sorted(ids))  # the saved ones are listed too
        self.assertNotIn(ids[0], runner._runs)  # dropped from memory...
        self.assertEqual(runner.view(ids[0])["status"], "done")  # ...but read back from the store

    def test_the_run_id_is_safe_to_use_as_a_file_name(self):
        runner = self.runner()
        run_id = runner.start(0.3)
        wait_for(runner, run_id, "done")
        self.assertTrue(reportstore.NAME.fullmatch(run_id + ".json"))

    def test_log_lines_of_a_run_carry_its_id(self):
        import logging

        runner = self.runner()
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger("evals")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.removeHandler, handler)
        run_id = runner.start(0.3)
        wait_for(runner, run_id, "done")
        self.assertTrue(records)
        self.assertTrue(all(record.job == run_id for record in records))


if __name__ == "__main__":
    unittest.main()
