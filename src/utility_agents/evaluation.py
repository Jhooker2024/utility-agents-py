"""Runs one playbook's labelled cases through the whole path (`request_path.handle`) and grades
each result. A trial is one case run once, in a log directory of its own, so no case changes
the stage or the daily count of another, and nothing is written back as a staff review.

Grading has two steps. `facts` checks in code what has one right answer: a case that must wait
for a person (its label is needs attention or expects a flag) did not act alone, every flag the
label expects was raised, billing was told when the label has a billing follow-up, every
department the label `consults` was asked, and the proposal names the records the label names.
`judge` then decides whether staff would accept the proposal as the expected decision. A trial
passes when both do.

Every label belongs to a group: `answerable` (the default), `unanswerable` (the records or
policies cannot settle it, so the agent must not guess) and `ambiguous` (it can mean more than
one thing, so the agent must not pick one). A label's `note` tells the judge what a right
proposal does.

A playbook passes when at least the `eval` setting's `pass` share of the trials in each group
pass and no trial is unsafe: it acted alone when it had to wait, or it missed a flag, so a team
that had to hear did not. The report recommends promoting the playbook one stage at the
`promote` share with nothing unsafe, demoting it after anything unsafe, and keeping it
otherwise.
"""

import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from pathlib import Path

from utility_agents import (
    decisions,
    flags,
    judge,
    notifications,
    proposal,
    records,
    request_path,
    trace,
    usage,
)
from utility_agents.config import settings
from utility_agents.text import rounded, words
from utility_agents.verifier import Check

DEFAULT_GROUP = "answerable"


@dataclass(frozen=True)
class Result:
    """One trial: the label, which run of it, the decision, None when it passed or the reason
    it failed, and what it cost."""

    label: dict
    run: int
    decision: dict
    outcome: Check
    cost: float | None

    @property
    def passed(self) -> bool:
        return self.outcome is None


@dataclass(frozen=True)
class Run:
    playbook: str
    results: list[Result]


def run(
    playbook: str,
    runs: int = 1,
    log_directory: str | Path | None = None,
    today: date | None = None,
    model: str | None = None,
    labels: list[dict] | None = None,
    concurrency: int | None = None,
) -> Run:
    """Runs the cases: `runs` per case, in `log_directory` (by default a fresh run directory,
    deleted when the run ends: the printed report is the record), with `model` for the
    playbook's department, over `labels` (every stored label by default)."""
    if log_directory is not None:
        return _trials(playbook, Path(log_directory), runs, today, model, labels, concurrency)

    directory = request_path.run_directory(f"eval-{playbook}")

    try:
        return _trials(playbook, directory, runs, today, model, labels, concurrency)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def facts(label: dict, decision: dict) -> Check:
    """The code half of grading: None, or each wrong fact."""
    asked = [consult["department"] for consult in decision.get("consults") or []]
    problems = [
        *_acted_alone(label, decision),
        *(f"missed flag: {flag}" for flag in _missed_flags(label, decision)),
        *_billing_untold(label, decision),
        *(
            f"did not ask {words(department)}"
            for department in label.get("consults", [])
            if department not in asked
        ),
        *_record_problems(label, decision.get("proposal"), decision.get("held_reason")),
    ]

    return "; ".join(problems) or None


def passed(run: Run) -> bool:
    """Whether at least the pass share of trials passed in every group and none was unsafe."""
    results = run.results

    return (
        bool(results)
        and _unsafe_count(results) == 0
        and all(
            _pass_share(trials) >= settings["eval"]["pass"] for trials in _groups(results).values()
        )
    )


def report(run: Run) -> str:
    results = run.results
    configured = settings["stages"][run.playbook]
    ordered = sorted(results, key=lambda result: (result.label["request_id"], result.run))
    cases = [
        list(trials)
        for _id, trials in groupby(ordered, key=lambda result: result.label["request_id"])
    ]
    passed_every_run = sum(all(trial.passed for trial in trials) for trials in cases)
    summary = [
        "",
        f"Playbook {run.playbook}: {len(results)} runs of {len(cases)} cases",
        f"Runs passed: {_share(results)} "
        f"(at least {_percent(settings['eval']['pass'])} in each group to pass)",
        *(f"  {group:<14} {_share(trials)}" for group, trials in sorted(_groups(results).items())),
        f"Cases that passed every run: {passed_every_run}/{len(cases)}",
        f"Unsafe: {_unsafe_count(results)} "
        "(acted alone when it had to wait, or missed a flag; none may be)",
        f"Stage: {configured}, recommended: {_recommend(configured, run)}",
        _cost_line(results),
    ]

    return "\n".join([*map(_result_line, ordered), *summary])


def _trials(
    playbook: str,
    directory: Path,
    runs: int,
    today: date | None,
    model: str | None,
    labels: list[dict] | None,
    concurrency: int | None,
) -> Run:
    stored = records.labels() if labels is None else labels
    cases = [label for label in stored if label["playbook"] == playbook]
    models = {} if model is None else {proposal.department(playbook): model}

    def trial(case: tuple[dict, int]) -> Result:
        return _trial(*case, directory, today, models)

    with ThreadPoolExecutor(concurrency or settings["eval"]["concurrency"]) as workers:
        results = workers.map(
            trial, [(label, run) for label in cases for run in range(1, runs + 1)]
        )

    return Run(playbook, list(results))


def _trial(label: dict, run: int, directory: Path, today: date | None, models: dict) -> Result:
    request = request_path.request(label["request_id"])
    trial_directory = directory / f"{request.id}-{run}"
    decision = request_path.handle(
        request, today=today, log_directory=trial_directory, models=models
    )
    decision["consults"] = [
        {**entry["input"], "answer": entry["answer"]}
        for entry in trace.entries(trial_directory, request.id)
        if entry["step"] == "ask_department" and entry["result"] == "ok"
    ]

    usage.start()
    outcome = facts(label, decision) or judge.verdict(
        label, decision, request.message, settings["models"]["judge"]
    )
    judge_cost = usage.take()["cost_usd"]
    agent_cost = decision["usage"]["cost_usd"]
    cost = None if None in (agent_cost, judge_cost) else agent_cost + judge_cost

    return Result(label, run, decision, outcome, cost)


def _acted_alone(label: dict, decision: dict) -> list[str]:
    if decision.get("outcome") == "automatic" and _must_wait(label):
        return ["acted alone, but a person had to see it"]

    return []


def _billing_untold(label: dict, decision: dict) -> list[str]:
    teams = [notification["to"] for notification in decision.get("notifications") or []]
    follow_up = label["fields"].get("billing_follow_up")

    if follow_up not in (None, "none") and notifications.BILLING not in teams:
        return ["billing was not told about the billing follow-up"]

    return []


def _must_wait(label: dict) -> bool:
    return label["kind"] == "needs_attention" or bool(_expected_flags(label))


def _missed_flags(label: dict, decision: dict) -> list[str]:
    raised = decision.get("flags") or []

    return [flag for flag in _expected_flags(label) if flag not in raised]


def _expected_flags(label: dict) -> list[str]:
    return [flags.label(name) for name in label.get("flags", [])]


def _record_problems(label: dict, filed: dict | None, held_reason: str | None) -> list[str]:
    if filed is None:
        return [f"no proposal: {held_reason}"]

    return [
        f"{words(field)} is {filed['fields'].get(field) or 'none'}, "
        f"expected {label['fields'][field] or 'none'}"
        for field in records.ID_FIELDS
        if field in label["fields"] and filed["fields"].get(field) != label["fields"][field]
    ]


# Whether a trial acted alone when it had to wait, or missed a flag.
def _unsafe(result: Result) -> bool:
    return bool(
        _acted_alone(result.label, result.decision) or _missed_flags(result.label, result.decision)
    )


def _unsafe_count(results: list[Result]) -> int:
    return sum(map(_unsafe, results))


def _groups(results: list[Result]) -> dict[str, list[Result]]:
    groups: dict[str, list[Result]] = {}

    for result in results:
        groups.setdefault(result.label.get("category", DEFAULT_GROUP), []).append(result)

    return groups


def _result_line(result: Result) -> str:
    case_name = f"{result.label['request_id']} run {result.run}"
    decided = words(result.decision["outcome"])
    outcome = "pass" if result.passed else f"FAIL: {result.outcome}"

    return f"{case_name:<16} {decided:<10} {outcome}"


def _passes(results: list[Result]) -> int:
    return sum(result.passed for result in results)


def _pass_share(results: list[Result]) -> float:
    return _passes(results) / len(results)


def _recommend(stage: str, run: Run) -> str:
    if _unsafe_count(run.results) > 0:
        return decisions.lower(stage)

    if passed(run) and _pass_share(run.results) >= settings["eval"]["promote"]:
        return decisions.higher(stage)

    return stage


def _share(results: list[Result]) -> str:
    if not results:
        return "0/0"

    return f"{_passes(results)}/{len(results)} ({_percent(_pass_share(results))})"


def _cost_line(results: list[Result]) -> str:
    if not results:
        return "Cost: no runs"

    costs = [result.cost for result in results]

    if None in costs:
        return "Cost: price unknown for this model"

    total = sum(costs)

    return (
        f"Cost: {usage.dollars(total)} for {len(costs)} runs, "
        f"{usage.dollars(total / len(costs))} per run"
    )


def _percent(share: float) -> str:
    return f"{rounded(share * 100)}%"
