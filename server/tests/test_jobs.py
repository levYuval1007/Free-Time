import os
import sys
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import jobs
import ors
import places


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def wait_until_done(store, job_id, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        job = store.get(job_id)
        if job.status in jobs.TERMINAL:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class StoreTests(unittest.TestCase):
    def test_new_jobs_start_queued(self):
        job, created = jobs.JobStore().create("req")
        self.assertTrue(created)
        self.assertEqual(job.status, jobs.QUEUED)

    def test_same_key_and_request_returns_the_same_job(self):
        store = jobs.JobStore()
        first, _ = store.create("req", "key-12345678")
        again, created = store.create("req", "key-12345678")
        self.assertFalse(created)
        self.assertIs(first, again)

    def test_same_key_with_another_request_conflicts(self):
        store = jobs.JobStore()
        store.create("req", "key-12345678")
        with self.assertRaises(jobs.KeyConflict):
            store.create("different", "key-12345678")

    def test_no_key_means_no_deduplication(self):
        store = jobs.JobStore()
        self.assertNotEqual(store.create("req")[0].id, store.create("req")[0].id)

    def test_backpressure_counts_only_active_jobs(self):
        store = jobs.JobStore(max_active=2)
        first, _ = store.create("a")
        store.create("b")
        with self.assertRaises(jobs.Busy):
            store.create("c")
        store.start(first.id)
        store.finish(first.id, jobs.SUCCEEDED, result={})
        store.create("c")  # a finished job frees a slot

    def test_transitions_are_enforced(self):
        store = jobs.JobStore()
        job, _ = store.create("a")
        with self.assertRaises(jobs.IllegalTransition):
            store.finish(job.id, jobs.SUCCEEDED)  # cannot skip running
        store.start(job.id)
        store.finish(job.id, jobs.DEGRADED, result={"x": 1}, degraded_reason="refused")
        with self.assertRaises(jobs.IllegalTransition):
            store.finish(job.id, jobs.FAILED)
        with self.assertRaises(jobs.IllegalTransition):
            store.start(job.id)
        self.assertEqual(store.get(job.id).degraded_reason, "refused")

    def test_stage_is_only_recorded_while_running(self):
        store = jobs.JobStore()
        job, _ = store.create("a")
        store.set_stage(job.id, "early")
        self.assertIsNone(store.get(job.id).stage)
        store.start(job.id)
        store.set_stage(job.id, "Searching")
        self.assertEqual(store.get(job.id).stage, "Searching")
        store.finish(job.id, jobs.SUCCEEDED, result={})
        self.assertIsNone(store.get(job.id).stage)

    def test_finished_jobs_expire_but_active_ones_do_not(self):
        clock = Clock()
        store = jobs.JobStore(ttl_seconds=60, clock=clock)
        done, _ = store.create("a", "key-aaaaaaaa")
        running, _ = store.create("b")
        store.start(done.id)
        store.finish(done.id, jobs.SUCCEEDED, result={})
        clock.now += 61
        self.assertIsNone(store.get(done.id))
        self.assertIsNotNone(store.get(running.id))
        # The expired job's key can be used again.
        self.assertTrue(store.create("a", "key-aaaaaaaa")[1])


def outcome(status="succeeded", result=None, reason=None):
    return SimpleNamespace(status=status, result=result or {"stops": []}, degraded_reason=reason)


class RunnerTests(unittest.TestCase):
    def run_work(self, work):
        store = jobs.JobStore()
        runner = jobs.JobRunner(store, workers=1)
        job, _ = store.create("x")
        runner.submit(job.id, work)
        return wait_until_done(store, job.id)

    def test_success(self):
        def work(progress):
            progress("Searching")
            return outcome(result={"stops": [1]})

        job = self.run_work(work)
        self.assertEqual((job.status, job.result), ("succeeded", {"stops": [1]}))

    def test_degraded_outcome_keeps_the_reason(self):
        job = self.run_work(lambda progress: outcome("degraded", reason="llm_unavailable"))
        self.assertEqual((job.status, job.degraded_reason), ("degraded", "llm_unavailable"))

    def test_upstream_errors_show_their_message(self):
        def route_down(progress):
            raise ors.RouteError("No route")

        def places_down(progress):
            raise places.PlacesError("Places is down", transient=True)

        self.assertEqual(self.run_work(route_down).error, "No route")
        self.assertEqual(self.run_work(places_down).error, "Places is down")

    def test_unexpected_errors_do_not_leak_details(self):
        def crash(progress):
            raise KeyError("secret internal detail")

        job = self.run_work(crash)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.error, jobs.GENERIC_ERROR)


if __name__ == "__main__":
    unittest.main()
