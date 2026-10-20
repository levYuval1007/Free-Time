import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import evalservice
import main
import reportstore
from test_evalservice import minimal_report

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class AdminApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.release = threading.Event()
        self.release.set()
        self.calls = []

        def run(max_usd, only, progress):
            self.calls.append((max_usd, only))
            self.release.wait(2)
            return minimal_report()

        self.runner = evalservice.EvalRunner(reportstore.FileReportStore(Path(self.temp.name)), run)
        patches = [
            mock.patch.object(evalservice, "runner", self.runner),
            mock.patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(main.app)

    def start(self, body=None):
        return self.client.post("/api/admin/evals", json=body or {}, headers=AUTH)

    def wait_done(self, run_id):
        for _ in range(300):
            if self.client.get(f"/api/admin/evals/{run_id}", headers=AUTH).json()["status"] != "running":
                return
            time.sleep(0.01)
        raise AssertionError("run did not finish")

    def test_the_endpoints_do_not_exist_without_a_configured_token(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("ADMIN_TOKEN", None)
            self.assertEqual(self.client.post("/api/admin/evals", json={}, headers=AUTH).status_code, 404)
            self.assertEqual(self.client.get("/api/admin/evals", headers=AUTH).status_code, 404)
            self.assertEqual(self.client.get("/api/admin/evals/x", headers=AUTH).status_code, 404)
        self.assertEqual(self.calls, [])

    def test_a_missing_or_wrong_token_is_unauthorized_and_runs_nothing(self):
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}):
            res = self.client.post("/api/admin/evals", json={}, headers=headers)
            self.assertEqual(res.status_code, 401, headers)
            self.assertEqual(res.json(), {"error": "Unauthorized"})
            self.assertEqual(self.client.get("/api/admin/evals", headers=headers).status_code, 401)
        self.assertEqual(self.calls, [])

    def test_starting_returns_an_id_and_the_run_uses_the_defaults(self):
        res = self.start()
        self.assertEqual(res.status_code, 202)
        body = res.json()
        self.assertEqual(body["status"], "running")
        self.wait_done(body["id"])
        self.assertEqual(self.calls, [(0.30, None)])

    def test_the_budget_and_filter_are_passed_on(self):
        run_id = self.start({"max_usd": 0.5, "only": "kids"}).json()["id"]
        self.wait_done(run_id)
        self.assertEqual(self.calls, [(0.5, "kids")])

    def test_the_budget_is_limited(self):
        for bad in ({"max_usd": 5}, {"max_usd": 0.01}, {"max_usd": -1}, {"max_usd": "lots"}, {"only": "x" * 41}):
            res = self.start(bad)
            self.assertEqual(res.status_code, 400, bad)
            self.assertIn("error", res.json())
        self.assertEqual(self.calls, [])

    def test_the_status_and_the_report_can_be_read(self):
        run_id = self.start().json()["id"]
        self.wait_done(run_id)
        view = self.client.get(f"/api/admin/evals/{run_id}", headers=AUTH).json()
        self.assertEqual(view["status"], "done")
        self.assertEqual(view["report"]["model"], "claude-sonnet-5")
        self.assertNotIn("markdown", view)

    def test_the_markdown_can_be_downloaded(self):
        run_id = self.start().json()["id"]
        self.wait_done(run_id)
        res = self.client.get(f"/api/admin/evals/{run_id}?format=md", headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.headers["content-type"].startswith("text/markdown"))
        self.assertIn("# Leeway: AI agent vs rule-based planner", res.text)

    def test_the_markdown_is_not_available_while_the_run_is_going(self):
        self.release.clear()
        run_id = self.start().json()["id"]
        res = self.client.get(f"/api/admin/evals/{run_id}?format=md", headers=AUTH)
        self.assertEqual(res.status_code, 409)
        self.assertIn("running", res.json()["error"])
        self.release.set()
        self.wait_done(run_id)

    def test_a_second_run_while_one_is_going_is_refused(self):
        self.release.clear()
        first = self.start()
        second = self.start()
        self.assertEqual((first.status_code, second.status_code), (202, 409))
        self.assertIn("already running", second.json()["error"])
        self.release.set()
        self.wait_done(first.json()["id"])

    def test_unknown_runs_and_bad_formats(self):
        self.assertEqual(self.client.get("/api/admin/evals/eval-nope", headers=AUTH).status_code, 404)
        run_id = self.start().json()["id"]
        self.wait_done(run_id)
        self.assertEqual(self.client.get(f"/api/admin/evals/{run_id}?format=xml", headers=AUTH).status_code, 400)

    def test_the_list_shows_recent_runs_without_their_reports(self):
        run_id = self.start().json()["id"]
        self.wait_done(run_id)
        listed = self.client.get("/api/admin/evals", headers=AUTH).json()["runs"]
        self.assertEqual([run["id"] for run in listed], [run_id])
        self.assertNotIn("report", listed[0])
        self.assertEqual(listed[0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
