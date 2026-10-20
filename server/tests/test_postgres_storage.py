import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import evalservice
import main
import reportstore
from test_evalservice import minimal_report, wait_for

URL = "postgresql://leeway_user:s3cret-password@db.example.test/leeway?sslmode=require"
TOKEN = "storage-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, database):
        self.database = database

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.database.closed += 1
        return False

    def execute(self, sql, params=()):
        db = self.database
        db.statements.append((sql, tuple(params)))
        text = " ".join(sql.split())
        if text.startswith("CREATE TABLE"):
            db.created += 1
            return FakeCursor([])
        if text.startswith("INSERT INTO leeway_reports"):
            name, body = params
            db.clock += 1
            db.rows[name] = (body, db.clock)
            return FakeCursor([])
        if text.startswith("SELECT body"):
            row = db.rows.get(params[0])
            return FakeCursor([(row[0],)] if row else [])
        if text.startswith("SELECT name"):
            ordered = sorted(db.rows.items(), key=lambda item: item[1][1], reverse=True)
            return FakeCursor([(name,) for name, _ in ordered[: params[0]]])
        if text.startswith("SELECT count(*)"):
            return FakeCursor([(len(db.rows),)])
        raise AssertionError(f"unexpected SQL: {sql}")


class FakeDatabase:
    """Just enough of a database for the store: named text documents."""

    def __init__(self):
        self.rows = {}
        self.statements = []
        self.urls = []
        self.created = 0
        self.closed = 0
        self.clock = 0
        self.fail_with = None

    def connect(self, url):
        self.urls.append(url)
        if self.fail_with:
            raise self.fail_with
        return FakeConnection(self)

    def store(self):
        return reportstore.PostgresReportStore(URL, connect=self.connect)


class PostgresStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.store = self.db.store()

    def test_saves_and_reads_back(self):
        self.assertEqual(self.store.save("eval-1.md", "# Report\nשלום"), "postgres:eval-1.md")
        self.assertEqual(self.store.read("eval-1.md"), "# Report\nשלום")

    def test_a_missing_report_reads_as_none(self):
        self.assertIsNone(self.store.read("nope.md"))
        self.assertEqual(self.store.names(), [])

    def test_saving_again_replaces_the_report(self):
        self.store.save("a.md", "one")
        self.store.save("a.md", "two")
        self.assertEqual(self.store.read("a.md"), "two")
        self.assertEqual(len(self.db.rows), 1)

    def test_names_come_back_newest_first(self):
        for name in ("old.md", "mid.md", "new.md"):
            self.store.save(name, name)
        self.assertEqual(self.store.names(), ["new.md", "mid.md", "old.md"])

    def test_the_table_is_created_once_per_store(self):
        self.store.save("a.md", "x")
        self.store.read("a.md")
        self.store.names()
        self.assertEqual(self.db.created, 1)

    def test_every_connection_is_closed_after_use(self):
        self.store.save("a.md", "x")
        self.store.read("a.md")
        self.store.check()
        self.assertEqual(self.db.closed, len(self.db.urls))

    def test_the_configured_url_is_the_one_used(self):
        self.store.read("a.md")
        self.assertEqual(set(self.db.urls), {URL})

    def test_values_travel_as_parameters_never_inside_the_sql(self):
        self.store.save("eval-1.md", "body with 'quotes'; DROP TABLE leeway_reports; --")
        self.store.read("eval-1.md")
        for sql, params in self.db.statements:
            self.assertNotIn("eval-1", sql)
            self.assertNotIn("DROP", sql)
        self.assertTrue(any("eval-1.md" in params for _, params in self.db.statements))

    def test_names_that_are_not_safe_are_refused_before_any_connection(self):
        for bad in ("../x.md", "a/b", "'; DROP TABLE leeway_reports; --", "", ".hidden", "x" * 81):
            with self.assertRaises(ValueError, msg=bad):
                self.store.save(bad, "x")
            with self.assertRaises(ValueError, msg=bad):
                self.store.read(bad)
        self.assertEqual(self.db.urls, [])

    def test_the_connection_string_never_appears_when_the_store_is_shown(self):
        self.assertNotIn("s3cret", repr(self.store))
        self.assertNotIn("s3cret", str(self.store.check()))

    def test_check_reports_how_many_reports_are_saved(self):
        self.store.save("a.md", "x")
        self.assertEqual(self.store.check(), {"kind": "postgres", "ok": True, "reports": 1})

    def test_check_names_the_kind_of_error_without_its_text(self):
        self.db.fail_with = OSError(f"could not connect to {URL}")
        with self.assertLogs("reportstore", level="WARNING"):
            result = self.store.check()
        self.assertEqual(result, {"kind": "postgres", "ok": False, "error": "OSError"})
        self.assertNotIn("s3cret", str(result))

    def test_errors_from_the_database_reach_the_caller_of_save_and_read(self):
        self.db.fail_with = OSError("down")
        with self.assertRaises(OSError):
            self.store.save("a.md", "x")
        with self.assertRaises(OSError):
            self.store.read("a.md")

    def test_a_missing_driver_gives_a_clear_error(self):
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            with self.assertRaises(RuntimeError) as caught:
                reportstore._connect_psycopg(URL)
        self.assertIn("psycopg is not installed", str(caught.exception))
        self.assertNotIn("s3cret", str(caught.exception))


class StoreSelectionTests(unittest.TestCase):
    def test_a_database_url_selects_postgres(self):
        with mock.patch.dict(os.environ, {"DATABASE_URL": URL}):
            store = reportstore.default_store()
        self.assertEqual(store.kind, "postgres")

    def test_without_a_database_url_files_are_used(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DATABASE_URL", None)
            store = reportstore.default_store()
        self.assertEqual(store.kind, "files")

    def test_the_file_store_checks_out_too(self):
        with tempfile.TemporaryDirectory() as folder:
            store = reportstore.FileReportStore(folder)
            store.save("a.md", "x")
            self.assertEqual(store.check(), {"kind": "files", "ok": True, "reports": 1})


class ServiceKeepsReportsAcrossRestartsTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()

    def runner(self):
        return evalservice.EvalRunner(self.db.store(), lambda **kwargs: minimal_report())

    def finished_run(self):
        first = self.runner()
        run_id = first.start(0.3)
        wait_for(first, run_id, "done")
        return run_id

    def test_the_report_is_saved_in_the_database_in_both_formats(self):
        run_id = self.finished_run()
        self.assertEqual(sorted(self.db.rows), [f"{run_id}.json", f"{run_id}.md"])
        self.assertEqual(json.loads(self.db.rows[f"{run_id}.json"][0])["model"], "claude-sonnet-5")

    def test_after_a_restart_the_run_is_listed_and_readable(self):
        run_id = self.finished_run()
        restarted = self.runner()  # a new process: nothing in memory
        listed = restarted.recent()
        self.assertEqual([run["id"] for run in listed], [run_id])
        self.assertEqual(listed[0]["status"], "done")
        self.assertTrue(listed[0]["started"].startswith("20"))  # taken from the id
        self.assertIn("# Leeway: AI agent vs rule-based planner", restarted.markdown(run_id))
        view = restarted.view(run_id)
        self.assertEqual(view["status"], "done")
        self.assertEqual(view["report"]["model"], "claude-sonnet-5")

    def test_a_run_in_memory_is_not_listed_twice(self):
        first = self.runner()
        run_id = first.start(0.3)
        wait_for(first, run_id, "done")
        self.assertEqual([run["id"] for run in first.recent()], [run_id])

    def test_ids_that_are_not_plain_never_reach_the_database(self):
        restarted = self.runner()
        for bad in ("../x", "a/b", "x y", "'; DROP TABLE leeway_reports; --"):
            self.assertIsNone(restarted.view(bad))
            self.assertIsNone(restarted.markdown(bad))
        self.assertEqual(self.db.urls, [])

    def test_an_unknown_id_is_none(self):
        self.assertIsNone(self.runner().view("eval-20260101-000000-abcd"))

    def test_a_database_that_cannot_be_listed_still_shows_the_runs_in_memory(self):
        runner = self.runner()
        run_id = runner.start(0.3)
        wait_for(runner, run_id, "done")
        self.db.fail_with = OSError("down")
        with self.assertLogs("evals", level="WARNING"):
            self.assertEqual([run["id"] for run in runner.recent()], [run_id])

    def test_a_database_that_cannot_be_read_gives_none_not_an_error(self):
        run_id = self.finished_run()
        restarted = self.runner()
        self.db.fail_with = OSError("down")
        with self.assertLogs("evals", level="WARNING"):
            self.assertIsNone(restarted.view(run_id))
            self.assertIsNone(restarted.markdown(run_id))

    def test_a_database_that_cannot_be_written_does_not_lose_the_report(self):
        self.db.fail_with = OSError("down")
        runner = self.runner()
        with self.assertLogs("evals", level="WARNING"):
            run_id = runner.start(0.3)
            view = wait_for(runner, run_id, "done")
        self.assertEqual(view["files"], [])
        self.assertIsNotNone(runner.markdown(run_id))

    def test_the_storage_kind_and_check_come_from_the_store(self):
        runner = self.runner()
        self.assertEqual(runner.storage_kind, "postgres")
        self.assertEqual(runner.storage_check(), {"kind": "postgres", "ok": True, "reports": 0})


class StorageEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.runner = evalservice.EvalRunner(self.db.store(), lambda **kwargs: minimal_report())
        for patch in (
            mock.patch.object(evalservice, "runner", self.runner),
            mock.patch.dict(os.environ, {"ADMIN_TOKEN": TOKEN}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.client = TestClient(main.app)

    def test_the_storage_check_needs_the_token(self):
        self.assertEqual(self.client.get("/api/admin/storage").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/storage", headers={"Authorization": "Bearer nope"}).status_code, 401)
        with mock.patch.dict(os.environ):
            os.environ.pop("ADMIN_TOKEN", None)
            self.assertEqual(self.client.get("/api/admin/storage", headers=AUTH).status_code, 404)
        self.assertEqual(self.db.urls, [])

    def test_the_storage_check_reports_the_database(self):
        res = self.client.get("/api/admin/storage", headers=AUTH)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"kind": "postgres", "ok": True, "reports": 0})

    def test_a_broken_database_is_reported_without_details(self):
        self.db.fail_with = OSError(f"could not connect to {URL}")
        with self.assertLogs("reportstore", level="WARNING"):
            res = self.client.get("/api/admin/storage", headers=AUTH)
        self.assertEqual(res.json(), {"kind": "postgres", "ok": False, "error": "OSError"})
        self.assertNotIn("s3cret", res.text)

    def test_the_list_names_the_storage_kind(self):
        self.assertEqual(self.client.get("/api/admin/evals", headers=AUTH).json(), {"runs": [], "storage": "postgres"})

    def test_a_report_from_before_a_restart_can_be_downloaded(self):
        first = self.client.post("/api/admin/evals", json={}, headers=AUTH).json()["id"]
        wait_for(self.runner, first, "done")
        restarted = evalservice.EvalRunner(self.db.store(), lambda **kwargs: minimal_report())
        with mock.patch.object(evalservice, "runner", restarted):
            listed = self.client.get("/api/admin/evals", headers=AUTH).json()["runs"]
            self.assertEqual([run["id"] for run in listed], [first])
            res = self.client.get(f"/api/admin/evals/{first}?format=md", headers=AUTH)
            self.assertEqual(res.status_code, 200)
            self.assertIn("# Leeway: AI agent vs rule-based planner", res.text)
            view = self.client.get(f"/api/admin/evals/{first}", headers=AUTH).json()
            self.assertEqual(view["status"], "done")

    def test_the_page_offers_the_storage_check(self):
        html = self.client.get("/admin/evals").text
        self.assertIn('id="check"', html)
        self.assertIn("/api/admin/storage", html)


if __name__ == "__main__":
    unittest.main()
