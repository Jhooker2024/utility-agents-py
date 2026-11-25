"""Append-only JSON lines files: one JSON object per line."""

import json
from pathlib import Path


def encode(entry: object) -> str:
    """One entry as a line of JSON. A date is written as its ISO text."""
    return json.dumps(entry, ensure_ascii=False, default=str)


def compact(value: object) -> str:
    """A value as JSON on one line with its keys in order, so the same value always reads
    the same."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def append(path: Path, entries: list[dict]) -> None:
    if not entries:
        return

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.writelines(encode(entry) + "\n" for entry in entries)


def read(path: Path) -> list[dict]:
    """Every entry in the file, oldest first; none when the file does not exist yet."""
    if not path.exists():
        return []

    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file]
