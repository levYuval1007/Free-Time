import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import jobs
import limits
import main
import places
import planning

ARRIVE = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
BODY = {"from_lon": 34.78, "from_lat": 32.08, "to_lon": 35.21, "to_lat": 31.77, "arrive_by": ARRIVE, "preferences": "quiet"}
BUDGET = {"status": "ok", "drive_minutes": 40, "buffer_minutes": 15, "free_minutes": 120}


def done(result=None):
    return SimpleNamespace(status="succeeded", result=result or {"budget": BUDGET, "stops": [], "source": "agent"}, degraded_reason=None)


class JobApiTests(unittest.TestCase):
    def setUp(self):
        main.store = jobs.JobStore(max_active=2)
        main.runner = jobs.JobRunner(main.store, workers=2)
        self.client = TestClient(main.app)
        self.original = planning.execute_plan
        self.seen = []

        def fake(request, progress):
            self.seen.append(request)
            progress("Searching for places")
            return done()

        planning.execute_plan = fake
        self.original_guard = limits.guard
        limits.guard = limits.Guard(per_ip_per_hour=2, plans_per_day=100, daily_tokens=1)

    def tearDown(self):
        planning.execute_plan = self.original
        limits.guard = self.original_guard

    def poll(self, job_id):
        for _ in range(300):
            body = self.client.get(f"/api/plans/{job_id}").json()
            if body["status"] in ("succeeded", "degraded", "failed"):
                return body
            time.sleep(0.01)
        raise AssertionError("job did not finish")

    def test_create_and_poll(self):
        res = self.client.post("/api/plans", json=BODY)
        self.assertEqual(res.status_code, 202)
        finished = self.poll(res.json()["job_id"])
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["result"]["source"], "agent")
        self.assertEqual(self.seen[0].preferences, "quiet")

    def test_idempotency_key_replays_the_same_job(self):
        headers = {"Idempotency-Key": "abcdefgh-1234"}
        first = self.client.post("/api/plans", json=BODY, headers=headers)
        again = self.client.post("/api/plans", json=BODY, headers=headers)
        self.assertEqual((first.status_code, again.status_code), (202, 200))
        self.assertEqual(first.json()["job_id"], again.json()["job_id"])
        self.poll(first.json()["job_id"])
        self.assertEqual(len(self.seen), 1)  # the agent ran once

    def test_key_reuse_with_another_request_conflicts(self):
        headers = {"Idempotency-Key": "abcdefgh-1234"}
        self.client.post("/api/plans", json=BODY, headers=headers)
        other = self.client.post("/api/plans", json={**BODY, "preferences": "loud"}, headers=headers)
        self.assertEqual(other.status_code, 409)
        self.assertIn("error", other.json())

    def test_validation_errors_use_the_common_shape(self):
        self.assertEqual(self.client.post("/api/plans", json={**BODY, "from_lat": 999}).status_code, 400)
        self.assertEqual(self.client.post("/api/plans", json={**BODY, "arrive_by": "tomorrow"}).status_code, 400)
        self.assertEqual(self.client.post("/api/plans", json={**BODY, "arrive_by": "2026-01-01T10:00:00"}).status_code, 400)
        self.assertEqual(self.client.post("/api/plans", json={**BODY, "preferences": "x" * 501}).status_code, 400)
        bad_key = self.client.post("/api/plans", json=BODY, headers={"Idempotency-Key": "short"})
        self.assertEqual(bad_key.status_code, 400)
        self.assertIn("error", bad_key.json())

    def test_too_many_plans_from_one_address_get_429(self):
        self.assertEqual(self.client.post("/api/plans", json=BODY).status_code, 202)
        self.assertEqual(self.client.post("/api/plans", json=BODY).status_code, 202)
        limited = self.client.post("/api/plans", json=BODY)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("error", limited.json())
        self.assertGreater(int(limited.headers["Retry-After"]), 0)

    def test_replaying_a_key_is_not_blocked_or_counted(self):
        headers = {"Idempotency-Key": "abcdefgh-1234"}
        first = self.client.post("/api/plans", json=BODY, headers=headers)
        for _ in range(5):
            self.assertEqual(self.client.post("/api/plans", json=BODY, headers=headers).status_code, 200)
        self.assertEqual(limits.guard.snapshot()["plans_today"], 1)
        self.assertEqual(first.status_code, 202)

    def test_unknown_job_is_404(self):
        res = self.client.get("/api/plans/nope")
        self.assertEqual(res.status_code, 404)
        self.assertIn("plan again", res.json()["error"].lower())

    def test_busy_server_answers_503_with_retry_after(self):
        limits.guard = limits.Guard(per_ip_per_hour=10, plans_per_day=100, daily_tokens=1)
        planning.execute_plan = lambda request, progress: time.sleep(0.3) or done()
        self.assertEqual(self.client.post("/api/plans", json=BODY).status_code, 202)
        self.assertEqual(self.client.post("/api/plans", json=BODY).status_code, 202)
        busy = self.client.post("/api/plans", json=BODY)
        self.assertEqual(busy.status_code, 503)
        self.assertEqual(busy.headers["Retry-After"], "10")
        time.sleep(0.5)

    def test_upstream_failure_is_reported_on_the_job(self):
        def broken(request, progress):
            raise places.PlacesError("Places is down", transient=True)

        planning.execute_plan = broken
        finished = self.poll(self.client.post("/api/plans", json=BODY).json()["job_id"])
        self.assertEqual((finished["status"], finished["error"]), ("failed", "Places is down"))


if __name__ == "__main__":
    unittest.main()
