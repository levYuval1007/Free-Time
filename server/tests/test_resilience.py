import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import http_client
import jobs
import ors
from test_jobs import wait_until_done


class FakeConnection:
    """Behaves as scripted: an exception to raise or a (status, body) answer."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome

    def getresponse(self):
        status, body = self.outcome
        return SimpleNamespace(status=status, read=lambda: body)

    def close(self):
        self.closed = True


class ScriptedClient(http_client.PooledClient):
    def __init__(self, *outcomes):
        super().__init__("example.test", timeout=7)
        self.created = []
        self._script = list(outcomes)

    def _new(self):
        connection = FakeConnection(self._script.pop(0))
        self.created.append(connection)
        return connection


class PooledClientTests(unittest.TestCase):
    def test_a_timeout_is_not_retried(self):
        client = ScriptedClient(TimeoutError("timed out"), (200, b"never reached"))
        with self.assertRaises(http_client.TransportError) as caught:
            client.request("GET", "/x")
        self.assertEqual(len(client.created), 1)
        self.assertIn("7 seconds", str(caught.exception))
        self.assertTrue(client.created[0].closed)

    def test_a_dropped_connection_is_retried_once_on_a_fresh_one(self):
        client = ScriptedClient(ConnectionResetError("reset"), (200, b"ok"))
        status, body = client.request("GET", "/x")
        self.assertEqual((status, body), (200, b"ok"))
        self.assertEqual(len(client.created), 2)

    def test_two_failures_raise(self):
        client = ScriptedClient(ConnectionResetError("a"), ConnectionResetError("b"))
        with self.assertRaises(http_client.TransportError):
            client.request("GET", "/x")
        self.assertEqual(len(client.created), 2)

    def test_a_good_connection_goes_back_to_the_pool(self):
        client = ScriptedClient((200, b"one"))
        client.request("GET", "/x")
        self.assertEqual(client._pool.qsize(), 1)


class OrsCallTests(unittest.TestCase):
    def setUp(self):
        sleep = mock.patch("ors.time.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def call_with(self, *answers):
        request = mock.Mock(side_effect=list(answers))
        with mock.patch.object(ors._client, "request", request):
            try:
                return ors._call("POST", "/v2/matrix/driving-car", b"{}"), request
            except ors.RouteError as err:
                return err, request

    def test_the_client_uses_a_short_timeout(self):
        self.assertEqual(ors._client.timeout, ors.ROUTE_TIMEOUT_S)
        self.assertLessEqual(ors.ROUTE_TIMEOUT_S, 10)

    def test_a_gateway_blip_is_retried_once_and_then_succeeds(self):
        for status in (502, 503, 504):
            result, request = self.call_with((status, b"<html>bad</html>"), (200, json.dumps({"ok": 1}).encode()))
            self.assertEqual(result, {"ok": 1})
            self.assertEqual(request.call_count, 2)

    def test_a_gateway_error_twice_gives_a_friendly_message_without_the_page(self):
        result, request = self.call_with((502, b"<html><title>502 Bad Gateway</title></html>"), (502, b"<html>again</html>"))
        self.assertIsInstance(result, ors.RouteError)
        self.assertEqual(str(result), ors.UNAVAILABLE_MESSAGE)
        self.assertNotIn("html", str(result).lower())
        self.assertNotIsInstance(result, ors.QuotaExceeded)
        self.assertEqual(request.call_count, 2)

    def test_other_server_errors_are_not_retried(self):
        result, request = self.call_with((500, b"boom"))
        self.assertEqual(str(result), ors.UNAVAILABLE_MESSAGE)
        self.assertEqual(request.call_count, 1)

    def test_client_errors_are_not_retried_and_keep_their_code(self):
        result, request = self.call_with((404, b'{"error":"no route"}'))
        self.assertIn("404", str(result))
        self.assertEqual(request.call_count, 1)

    def test_quota_errors_are_not_retried(self):
        result, request = self.call_with((429, b"slow"))
        self.assertIsInstance(result, ors.QuotaExceeded)
        self.assertEqual(request.call_count, 1)

    def test_a_timeout_fails_fast_with_the_friendly_message_and_a_log_line(self):
        request = mock.Mock(side_effect=http_client.TransportError("no answer within 10 seconds"))
        with mock.patch.object(ors._client, "request", request):
            with self.assertLogs("ors", level="WARNING") as logged:
                with self.assertRaises(ors.RouteError) as caught:
                    ors._call("POST", "/v2/directions/driving-car/geojson", b"{}")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(str(caught.exception), ors.UNAVAILABLE_MESSAGE)
        self.assertIn("unreachable", "\n".join(logged.output))
        self.assertIn("no answer within 10 seconds", "\n".join(logged.output))

    def test_the_retry_is_logged(self):
        with self.assertLogs("ors", level="WARNING") as logged:
            self.call_with((502, b"x"), (200, b"{}"))
        self.assertIn("trying once more", "\n".join(logged.output))

    def test_a_failure_log_is_one_line_with_a_short_body(self):
        with self.assertLogs("ors", level="WARNING") as logged:
            self.call_with((502, b"<html>\n<head>\n" + b"x" * 500 + b"</head></html>"), (502, b"<html>\n" + b"y" * 500))
        failure = [line for line in logged.output if "-> 502 <" in line][-1]
        self.assertNotIn("\n", failure)
        self.assertLess(len(failure), 400)


class JobFailureLogTests(unittest.TestCase):
    def test_the_reason_a_job_failed_is_in_the_log(self):
        def work(progress):
            raise ors.RouteError(ors.UNAVAILABLE_MESSAGE)

        store = jobs.JobStore()
        runner = jobs.JobRunner(store, workers=1)
        job, _ = store.create("x")
        with self.assertLogs("jobs", level="INFO") as logged:
            runner.submit(job.id, work)
            wait_until_done(store, job.id)
            # the final status line is written just after the job is marked finished
            for _ in range(100):
                if any("job=" in line and "status=failed" in line for line in logged.output):
                    break
                import time

                time.sleep(0.01)
        text = "\n".join(logged.output)
        self.assertIn("failed: The routing service is not responding", text)
        self.assertIn("status=failed", text)
        self.assertIn("error='The routing service is not responding", text)


if __name__ == "__main__":
    unittest.main()
