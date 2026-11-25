"""The review loop. `decisions.jsonl` under the log directory holds one line per decision (the
proposal, the checks and the gate's outcome) and one line per staff review of a decision (what
the person did, and the kind and fields they settled on).

Everything else is derived from those lines: the automatic actions today, which count toward
the daily cap; breaches, a rejected review of an automatic decision within `BREACH_WINDOW_DAYS`,
which drop a playbook one stage, run to walk and walk to crawl.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from utility_agents import json_lines

FILE_NAME = "decisions.jsonl"
BREACH_WINDOW_DAYS = 30
STAGES = ("crawl", "walk", "run")
ACTIONS = ("sent_unedited", "edited", "rejected")


class NoDecision(Exception):
    """A review named a request that has no stored decision."""


def find(directory: str | Path, request_id: str) -> dict | None:
    """The latest stored decision for a request, or None. A request worked again supersedes."""
    decisions = [
        entry
        for entry in _entries(directory)
        if entry["type"] == "decision" and entry["request_id"] == request_id
    ]

    return decisions[-1] if decisions else None


def record(directory: str | Path, decision: dict) -> dict:
    """Stores a decision and returns it as it reads back from the log."""
    return _append({**decision, "type": "decision"}, directory)


def review(directory: str | Path, request_id: str, review: dict) -> dict:
    """Stores a staff review (`action`, `kind`, `fields`, `date`) of a stored decision and
    returns it as it reads back from the log."""
    if find(directory, request_id) is None:
        raise NoDecision(f"No decision for {request_id}.")

    return _append({**review, "type": "review", "request_id": request_id}, directory)


def automatic_today(directory: str | Path, today: date) -> int:
    return sum(
        entry["type"] == "decision"
        and entry.get("outcome") == "automatic"
        and entry.get("date") == today.isoformat()
        for entry in _entries(directory)
    )


def stage(
    directory: str | Path, playbook: str | None, stage: str | None, today: date
) -> str | None:
    """The stage a playbook runs at: its configured stage, or one lower after a breach. Crawl
    cannot go lower, and a request sent to a person has no playbook or stage."""
    if stage in ("walk", "run") and _breached(directory, playbook, today):
        return lower(stage)

    return stage


def lower(stage: str) -> str:
    """One stage lower: run to walk, walk to crawl; crawl stays crawl."""
    return _moved(stage, -1)


def higher(stage: str) -> str:
    """One stage higher: crawl to walk, walk to run; run stays run."""
    return _moved(stage, 1)


def _moved(stage: str, steps: int) -> str:
    return STAGES[min(max(STAGES.index(stage) + steps, 0), len(STAGES) - 1)]


def _breached(directory: str | Path, playbook: str | None, today: date) -> bool:
    since = (today - timedelta(days=BREACH_WINDOW_DAYS)).isoformat()
    entries = _entries(directory)
    decisions = {
        entry["request_id"]: entry
        for entry in entries
        if entry["type"] == "decision" and playbook in (None, entry.get("playbook"))
    }

    return any(
        decisions[entry["request_id"]].get("outcome") == "automatic"
        and entry["action"] == "rejected"
        and entry["date"] >= since
        for entry in entries
        if entry["type"] == "review" and entry["request_id"] in decisions
    )


def _append(entry: dict, directory: str | Path) -> dict:
    json_lines.append(_path(directory), [entry])

    return json.loads(json_lines.encode(entry))


def _entries(directory: str | Path) -> list[dict]:
    return json_lines.read(_path(directory))


def _path(directory: str | Path) -> Path:
    return Path(directory) / FILE_NAME
