import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import http_client
import ors

COORDINATES = (34.8, 32.1, 35.2, 31.8)


def good_answer(minutes=42):
    body = {
        "features": [
            {
                "properties": {"summary": {"distance": 50000, "duration": minutes * 60}, "segments": [{"steps": []}]},
                "geometry": {"coordinates": [[34.8, 32.1], [35.2, 31.8]]},
            }
        ]
    }
    return 200, json.dumps(body).encode()


class FailureSharingTests(unittest.TestCase):
    def setUp(self):
        ors._route_cache.clear()
        ors._route_locks.clear()
        key = mock.patch.object(ors, "_key", return_value="k")
        key.start()
        self.addCleanup(key.stop)
        self.addCleanup(ors._route_cache.clear)
        self.addCleanup(ors._route_locks.clear)

    def run_threads(self, count, request):
        outcomes = []

        def ask():
            try:
                outcomes.append(ors.route_coords(*COORDINATES))
            except ors.RouteError as err:
                outcomes.append(err)

        with mock.patch.object(ors._client, "request", request):
            threads = [threading.Thread(target=ask) for _ in range(count)]
            started = time.perf_counter()
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        return outcomes, time.perf_counter() - started

    def test_requests_waiting_behind_a_failure_do_not_wait_out_their_own_timeout(self):
        def hangs(*args, **kwargs):
            time.sleep(0.3)  # stands for a request that times out
            raise http_client.TransportError("no answer within 10 seconds")

        request = mock.Mock(side_effect=hangs)
        outcomes, elapsed = self.run_threads(3, request)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(outcomes), 3)
        self.assertTrue(all(isinstance(o, ors.RouteError) for o in outcomes))
        self.assertLess(elapsed, 0.8)  # three separate attempts would have taken about 0.9 seconds

    def test_everyone_gets_the_same_friendly_message(self):
        request = mock.Mock(side_effect=http_client.TransportError("no answer"))
        outcomes, _ = self.run_threads(2, request)
        self.assertEqual({str(o) for o in outcomes}, {ors.UNAVAILABLE_MESSAGE})

    def test_a_shared_failure_is_logged_once_as_a_failure_and_once_as_shared(self):
        request = mock.Mock(side_effect=http_client.TransportError("no answer"))
        with self.assertLogs("ors", level="INFO") as logged:
            self.run_threads(2, request)
        text = "\n".join(logged.output)
        self.assertEqual(text.count("unreachable"), 1)
        self.assertIn("not asking again", text)

    def test_the_error_type_is_kept_for_quota_failures(self):
        request = mock.Mock(return_value=(429, b"slow down"))
        outcomes, _ = self.run_threads(2, request)
        self.assertEqual(request.call_count, 1)
        self.assertTrue(all(isinstance(o, ors.QuotaExceeded) for o in outcomes))

    def test_after_a_moment_the_next_request_really_tries_again(self):
        request = mock.Mock(side_effect=[http_client.TransportError("down"), good_answer()])
        with mock.patch.object(ors._client, "request", request):
            with self.assertRaises(ors.RouteError):
                ors.route_coords(*COORDINATES)
            for key, (expires, value) in list(ors._route_cache.items()):
                ors._route_cache[key] = (time.monotonic() - 1, value)
            result = ors.route_coords(*COORDINATES)
        self.assertEqual(result["minutes"], 42)
        self.assertEqual(request.call_count, 2)

    def test_a_failure_is_remembered_only_briefly(self):
        self.assertLessEqual(ors.ROUTE_FAILURE_TTL_S, 10)
        self.assertLess(ors.ROUTE_FAILURE_TTL_S, ors.ROUTE_CACHE_TTL_S)

    def test_a_success_after_a_failure_is_cached_as_before(self):
        request = mock.Mock(side_effect=[http_client.TransportError("down"), good_answer(), good_answer(99)])
        with mock.patch.object(ors._client, "request", request):
            with self.assertRaises(ors.RouteError):
                ors.route_coords(*COORDINATES)
            for key, (expires, value) in list(ors._route_cache.items()):
                ors._route_cache[key] = (time.monotonic() - 1, value)
            first = ors.route_coords(*COORDINATES)
            second = ors.route_coords(*COORDINATES)
        self.assertEqual((first["minutes"], second["minutes"]), (42, 42))
        self.assertEqual(request.call_count, 2)

    def test_other_routes_are_not_affected_by_a_failure(self):
        request = mock.Mock(side_effect=[http_client.TransportError("down"), good_answer()])
        with mock.patch.object(ors._client, "request", request):
            with self.assertRaises(ors.RouteError):
                ors.route_coords(*COORDINATES)
            other = ors.route_coords(10.0, 10.0, 11.0, 11.0)
        self.assertEqual(other["minutes"], 42)


if __name__ == "__main__":
    unittest.main()
