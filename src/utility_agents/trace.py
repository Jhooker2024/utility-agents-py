"""Tracing: one JSON line per step of a request in `trace.jsonl` under the log directory, with
the request ID, the step, its result and how many milliseconds it took. Consults and transfers
are steps like any tool call.
"""

import time
from collections.abc import Callable
from pathlib import Path

from utility_agents import json_lines

FILE_NAME = "trace.jsonl"
FIRST_STEP = "chief_of_staff"


def path(directory: str | Path) -> Path:
    return Path(directory) / FILE_NAME


def append(directory: str | Path, request_id: str, steps: list[dict]) -> None:
    json_lines.append(path(directory), [{**step, "request_id": request_id} for step in steps])


def entries(directory: str | Path, request_id: str) -> list[dict]:
    """Every step of the latest run of one request, oldest first. A request held without a
    proposal is worked again, and each run starts at the chief of staff."""
    steps = [
        entry for entry in json_lines.read(path(directory)) if entry["request_id"] == request_id
    ]
    starts = [index for index, entry in enumerate(steps) if entry["step"] == FIRST_STEP]

    return steps[starts[-1] :] if starts else steps


def timed[Result](step: str, work: Callable[[], Result]) -> tuple[Result, dict]:
    """Runs `work` and returns its result with the step it makes, named `step`."""
    started = time.monotonic()
    result = work()

    return result, {"step": step, "milliseconds": int((time.monotonic() - started) * 1000)}
