"""Where finished evaluation reports are kept: in a Postgres database when DATABASE_URL is set, otherwise in files.

Files (server/evals/results by default, or EVAL_RESULTS_DIR) are lost whenever a free host restarts, so on a free
Render service the database is what keeps reports across restarts. The report is also written to the log and can be
fetched from the admin endpoint while the process lives. Both stores offer the same four methods
(save, read, names, check), so another backend only has to provide those.

The database holds one small table of named text documents. Queries are parameterised, the connection string is a
secret that is never logged or returned, and psycopg is imported only when the database is actually used.
"""

import logging
import re
from pathlib import Path

import config

log = logging.getLogger("reportstore")

DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "evals" / "results"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
LIST_LIMIT = 200


def _checked(name: str) -> str:
    if not NAME.fullmatch(name):
        raise ValueError(f"not a valid report name: {name!r}")
    return name


def default_directory() -> Path:
    return Path(config.get("EVAL_RESULTS_DIR") or DEFAULT_DIRECTORY)


class FileReportStore:
    kind = "files"

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else default_directory()

    def _path(self, name: str) -> Path:
        return self.directory / _checked(name)

    def save(self, name: str, text: str) -> str:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def read(self, name: str):
        path = self._path(name)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def names(self) -> list[str]:
        """Saved report names, newest first."""
        if not self.directory.is_dir():
            return []
        files = [p for p in self.directory.iterdir() if p.is_file() and NAME.fullmatch(p.name)]
        return [p.name for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]

    def check(self) -> dict:
        return {"kind": self.kind, "ok": True, "reports": len(self.names())}


def _connect_psycopg(url):
    try:
        import psycopg
    except ImportError as err:
        raise RuntimeError("psycopg is not installed; install the server requirements") from err
    return psycopg.connect(url, connect_timeout=15)


class PostgresReportStore:
    kind = "postgres"

    def __init__(self, url, connect=None):
        self._url = url
        self._connect = connect or _connect_psycopg
        self._ready = False

    def __repr__(self):  # never show the connection string
        return "PostgresReportStore()"

    def _run(self, query, params=(), fetch=None):
        """One short connection per call: reports are rare, so a pool would only add things that can break."""
        with self._connect(self._url) as connection:
            if not self._ready:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS leeway_reports ("
                    "name text PRIMARY KEY, body text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())"
                )
                self._ready = True
            cursor = connection.execute(query, params)
            if fetch == "one":
                return cursor.fetchone()
            if fetch == "all":
                return cursor.fetchall()
            return None

    def save(self, name: str, text: str) -> str:
        self._run(
            "INSERT INTO leeway_reports (name, body) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET body = EXCLUDED.body, created_at = now()",
            (_checked(name), text),
        )
        return f"postgres:{name}"

    def read(self, name: str):
        row = self._run("SELECT body FROM leeway_reports WHERE name = %s", (_checked(name),), fetch="one")
        return row[0] if row else None

    def names(self) -> list[str]:
        rows = self._run(
            "SELECT name FROM leeway_reports ORDER BY created_at DESC LIMIT %s", (LIST_LIMIT,), fetch="all"
        )
        return [row[0] for row in rows]

    def check(self) -> dict:
        """Whether the database can be reached and used. Only the kind of error is returned, never its text."""
        try:
            row = self._run("SELECT count(*) FROM leeway_reports", fetch="one")
        except Exception as err:
            log.warning("report database check failed: %s: %s", type(err).__name__, err)
            return {"kind": self.kind, "ok": False, "error": type(err).__name__}
        return {"kind": self.kind, "ok": True, "reports": row[0] if row else 0}


def default_store():
    url = config.get("DATABASE_URL")
    return PostgresReportStore(url) if url else FileReportStore()
