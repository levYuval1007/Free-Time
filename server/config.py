import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def get(name: str) -> str | None:
    return os.environ.get(name) or None


load_env_file()
