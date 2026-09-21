"""In-memory jobs for slow planning runs: a small state machine, idempotency, backpressure and a worker pool.

Jobs live in memory, so a restart loses them; the client shows a "plan again" message when a job is unknown.
"""

import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import ors
import places

log = logging.getLogger("jobs")

QUEUED, RUNNING, SUCCEEDED, DEGRADED, FAILED = "queued", "running", "succeeded", "degraded", "failed"
TERMINAL = {SUCCEEDED, DEGRADED, FAILED}
TRANSITIONS = {
    QUEUED: {RUNNING, FAILED},
    RUNNING: TERMINAL,
    SUCCEEDED: set(),
    DEGRADED: set(),
    FAILED: set(),
}
GENERIC_ERROR = "Something went wrong while planning. Please try again."


class Busy(Exception):
    """Too many jobs are waiting or running."""


class KeyConflict(Exception):
    """An idempotency key was reused for a different request."""


class IllegalTransition(Exception):
    pass


@dataclass
class Job:
    id: str
    status: str = QUEUED
    stage: str | None = None
    result: dict | None = None
    error: str | None = None
    degraded_reason: str | None = None
    fingerprint: str = ""
    key: str | None = None
    created: float = 0.0
    finished: float | None = None


class JobStore:
    def __init__(self, ttl_seconds=1800, max_active=6, clock=time.monotonic):
        self._ttl = ttl_seconds
        self._max_active = max_active
        self._clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}

    def _purge(self):
        now = self._clock()
        for job_id, job in list(self._jobs.items()):
            if job.finished is not None and now - job.finished > self._ttl:
                del self._jobs[job_id]
                if job.key:
                    self._by_key.pop(job.key, None)

    def create(self, fingerprint: str, key: str | None = None):
        """Returns (job, created). The same key with the same request returns the existing job."""
        with self._lock:
            self._purge()
            if key and key in self._by_key:
                existing = self._jobs[self._by_key[key]]
                if existing.fingerprint != fingerprint:
                    raise KeyConflict("This Idempotency-Key was already used for a different request")
                return existing, False
            active = sum(1 for job in self._jobs.values() if job.status not in TERMINAL)
            if active >= self._max_active:
                raise Busy("Too many plans are being prepared right now")
            job = Job(id=secrets.token_urlsafe(12), fingerprint=fingerprint, key=key, created=self._clock())
            self._jobs[job.id] = job
            if key:
                self._by_key[key] = job.id
            return job, True

    def has_key(self, key: str) -> bool:
        with self._lock:
            self._purge()
            return key in self._by_key

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._purge()
            return self._jobs.get(job_id)

    def _move(self, job: Job, status: str):
        if status not in TRANSITIONS[job.status]:
            raise IllegalTransition(f"{job.status} -> {status}")
        job.status = status
        if status in TERMINAL:
            job.finished = self._clock()

    def start(self, job_id: str):
        with self._lock:
            self._move(self._jobs[job_id], RUNNING)

    def set_stage(self, job_id: str, stage: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == RUNNING:
                job.stage = stage

    def finish(self, job_id: str, status: str, result=None, error=None, degraded_reason=None):
        with self._lock:
            job = self._jobs[job_id]
            self._move(job, status)
            job.result, job.error, job.degraded_reason, job.stage = result, error, degraded_reason, None


class JobRunner:
    def __init__(self, store: JobStore, workers=3):
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="plan-job")

    def submit(self, job_id: str, work):
        """work(progress) returns an object with status, result and degraded_reason (see planning.PlanOutcome)."""
        self._pool.submit(self._run, job_id, work)

    def _run(self, job_id: str, work):
        store = self._store
        started = time.perf_counter()
        try:
            store.start(job_id)
            outcome = work(lambda text: store.set_stage(job_id, text))
            store.finish(job_id, outcome.status, result=outcome.result, degraded_reason=outcome.degraded_reason)
        except (ors.RouteError, places.PlacesError) as err:
            store.finish(job_id, FAILED, error=str(err))
        except Exception:
            log.exception("plan job %s crashed", job_id)
            try:
                store.finish(job_id, FAILED, error=GENERIC_ERROR)
            except IllegalTransition:
                pass
        job = store.get(job_id)
        log.info("job=%s status=%s ms=%d", job_id, job.status if job else "gone", (time.perf_counter() - started) * 1000)
