"""Runs the AI-vs-planner comparison in the background of the server, so it can be started and read over HTTP
(admin only) on a host where the paid API keys live, and keeps the finished reports.

One comparison runs at a time. Each finished report is saved as <id>.json and <id>.md through the report store, written
to the log line by line (the log outlives a restart where a free host's disk does not), and kept in memory.
"""

import json
import logging
import secrets
import threading
from datetime import datetime, timezone

import comparison
import jobtrace
import reportstore

log = logging.getLogger("evals")

KEEP_RUNS = 5  # finished runs kept in memory


class Busy(Exception):
    """A comparison is already running."""


class EvalRunner:
    def __init__(self, store=None, run=None):
        self._store = store or reportstore.FileReportStore()
        self._run = run or comparison.run_comparison
        self._lock = threading.Lock()
        self._runs = {}  # id -> record, oldest first

    def start(self, max_usd: float, only=None) -> str:
        with self._lock:
            if any(record["status"] == "running" for record in self._runs.values()):
                raise Busy("A comparison is already running")
            run_id = datetime.now(timezone.utc).strftime("eval-%Y%m%d-%H%M%S-") + secrets.token_hex(2)
            self._runs[run_id] = {
                "id": run_id,
                "status": "running",
                "progress": "Starting",
                "max_usd": max_usd,
                "only": only,
                "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "finished": None,
                "report": None,
                "markdown": None,
                "files": [],
                "error": None,
            }
            for old_id in list(self._runs)[:-KEEP_RUNS]:
                if self._runs[old_id]["status"] != "running":
                    del self._runs[old_id]
        threading.Thread(target=self._work, args=(run_id, max_usd, only), daemon=True, name=run_id).start()
        return run_id

    def _update(self, run_id, **fields):
        with self._lock:
            self._runs[run_id].update(fields)

    def _work(self, run_id, max_usd, only):
        jobtrace.current_job.set(run_id)
        try:
            report = self._run(
                max_usd=max_usd, only=only, progress=lambda text: self._update(run_id, progress=text)
            )
            markdown = comparison.render_markdown(report)
            files = self._save(run_id, report, markdown)
            for line in markdown.splitlines():
                log.info("report | %s", line)
            self._update(
                run_id, status="done", progress="Finished", report=report, markdown=markdown, files=files,
                finished=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
        except Exception:
            log.exception("comparison %s crashed", run_id)
            self._update(
                run_id, status="failed", progress="Failed", error="The comparison failed. See the server log.",
                finished=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )

    def _save(self, run_id, report, markdown):
        saved = []
        for name, text in ((f"{run_id}.json", json.dumps(report, indent=2, ensure_ascii=False)), (f"{run_id}.md", markdown)):
            try:
                saved.append(self._store.save(name, text))
            except OSError as err:
                log.warning("could not save %s: %s", name, err)
        return saved

    def view(self, run_id, with_report=True):
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            shown = {k: v for k, v in record.items() if k not in ("markdown",)}
            if not with_report:
                shown = {k: v for k, v in shown.items() if k != "report"}
            return dict(shown)

    def markdown(self, run_id):
        with self._lock:
            record = self._runs.get(run_id)
            return record["markdown"] if record else None

    def recent(self):
        with self._lock:
            return [
                {k: record[k] for k in ("id", "status", "progress", "started", "finished", "max_usd")}
                for record in reversed(list(self._runs.values()))
            ]


runner = EvalRunner()
