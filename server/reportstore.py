"""Where finished evaluation reports are kept.

The files go to a directory (server/evals/results by default, or EVAL_RESULTS_DIR). On a host whose disk is wiped
on every restart (a free Render service) they disappear with the process, so the report is also written to the log
and can be fetched from the admin endpoint while the process lives. Pointing EVAL_RESULTS_DIR at a persistent disk
keeps them. The class is small on purpose: another backend (a bucket or a database) only has to offer the same
three methods.
"""

import re
from pathlib import Path

import config

DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "evals" / "results"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def default_directory() -> Path:
    return Path(config.get("EVAL_RESULTS_DIR") or DEFAULT_DIRECTORY)


class FileReportStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else default_directory()

    def _path(self, name: str) -> Path:
        if not NAME.fullmatch(name):
            raise ValueError(f"not a valid report name: {name!r}")
        return self.directory / name

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
