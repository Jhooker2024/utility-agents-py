"""Runs utility requests through one path:

    request -> chief of staff -> department -> (transfer?) -> verifier -> gate -> trace + decisions

`request` loads a stored request by ID.

`handle` returns the stored decision when the request got a proposal before, without calling the
model again. A request held without one (no API key, a failed API call, the kill switch, a
person's queue) is worked again, because nothing about it was decided. Otherwise the department
works the request. When its proposal names another department in `transfer_to`, that department
works it once, with what was tried, and only its proposal becomes the decision. Every step goes
to the trace and the decision to the log.
"""

import dataclasses
import secrets
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from utility_agents import (
    chief_of_staff,
    decisions,
    department,
    flags,
    gate,
    notifications,
    proposal,
    records,
    trace,
    usage,
    verifier,
)
from utility_agents.config import settings
from utility_agents.text import day
from utility_agents.work import Context, Handoff, Request, Worked

FIELD_APP = "field_app"


class UnknownRequest(LookupError):
    """No stored request has the ID asked for."""


def request(request_id: str) -> Request:
    """The stored request with this ID."""
    stored = records.request(request_id)

    if stored is None:
        raise UnknownRequest(f"No request has ID {request_id}.")

    return Request(stored["id"], stored["channel"], stored.get("customer_id"), stored["message"])


def new_request(channel: str, message: str, customer_id: str | None) -> Request:
    """A new request typed in by a person, on a channel such as `field_app`, `email` or
    `hr_portal`. Its ID is `S-`, the time in milliseconds and a random suffix, so every
    submission is decided afresh, even two sent in the same millisecond. A field report is
    stamped with the day it was sent, which the playbook takes as the visit date when the
    report gives none."""
    request_id = f"S-{time.time_ns() // 1_000_000}-{secrets.token_hex(4)}"

    if channel == FIELD_APP:
        message = f"Sent from the field app on {day(utc_today())}.\n{message}"

    return Request(request_id, channel, customer_id, message)


def handle(
    request: Request,
    today: date | None = None,
    log_directory: str | Path | None = None,
    models: dict[str, str] | None = None,
) -> dict:
    """The decision for a request, as it reads back from the log. `today` and `log_directory`
    are for tests and the eval; `models` overrides the model of any role in the `models`
    setting."""
    context = Context(
        today=today or utc_today(),
        models={**settings["models"], **(models or {})},
        log_directory=str(log_directory or settings["log_directory"]),
    )
    stored = decisions.find(context.log_directory, request.id)

    if stored is not None and stored.get("proposal") is not None:
        return stored

    usage.start()

    return _decide(request, context)


def run_directory(name: str) -> Path:
    """A fresh directory under the log directory for one run, such as a demo or an eval. The
    random suffix keeps two runs started in the same second apart."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

    return Path(settings["log_directory"]) / f"{name}-{timestamp}-{secrets.token_hex(4)}"


def utc_today() -> date:
    """Today in UTC, the day a typed request and a staff review are dated."""
    return datetime.now(UTC).date()


def _decide(request: Request, context: Context) -> dict:
    routed, route_step = _traced(
        "chief_of_staff", lambda: chief_of_staff.route(request, context), _routed_text
    )
    worked, playbook, steps = _work(routed, request.id, context)
    filed = worked.proposal
    checks, verify_step = _traced(
        "verifier", lambda: verifier.verify(worked, request, context), _checks_text
    )
    raised = flags.raised(_concerns(routed, filed), request.channel, request.customer_id)
    conditions = gate.Conditions(
        stage=decisions.stage(
            context.log_directory, playbook, settings["stages"].get(playbook), context.today
        ),
        automatic_today=decisions.automatic_today(context.log_directory, context.today),
        daily_cap=settings["daily_cap"],
        flags=raised,
        transferred=any(step["step"] == "transfer" for step in steps),
    )
    (outcome, gate_reason), gate_step = _traced(
        "gate", lambda: gate.decide(filed, checks, conditions), ": ".join
    )

    trace.append(context.log_directory, request.id, [route_step, *steps, verify_step, gate_step])

    told = notifications.build(request.id, raised, filed)
    notifications.deliver(context.log_directory, request.id, told)

    return decisions.record(
        context.log_directory,
        {
            "request_id": request.id,
            "date": context.today,
            "playbook": playbook,
            "proposal": filed and filed.model_dump(mode="json"),
            "held_reason": worked.held_reason,
            "checks": {check: _check_text(result) for check, result in checks.items()},
            "stage": conditions.stage,
            "outcome": outcome,
            "gate_reason": gate_reason,
            "flags": [flag.label for flag in raised],
            "notifications": told,
            "usage": usage.take(),
        },
    )


def _traced[Result](
    step: str, work: Callable[[], Result], describe: Callable[[Result], str]
) -> tuple[Result, dict]:
    result, timed = trace.timed(step, work)

    return result, {**timed, "result": describe(result)}


def _work(
    routed: chief_of_staff.Routed | chief_of_staff.Person, request_id: str, context: Context
) -> tuple[Worked, str | None, list[dict]]:
    if isinstance(routed, chief_of_staff.Person):
        return Worked(held_reason=routed.reason), None, []

    worked, steps = _run(routed.playbook, routed.handoff, request_id, context)
    filed = worked.proposal

    if filed is None or filed.transfer_to is None:
        return worked, routed.playbook, steps

    tried = f"The {filed.department} agent passed it on: {filed.summary}"
    transfer = {"step": "transfer", "result": filed.transfer_to, "milliseconds": 0}
    playbook = proposal.request_playbook(filed.transfer_to)
    worked, more_steps = _run(
        playbook, dataclasses.replace(routed.handoff, tried=tried), request_id, context
    )

    return worked, playbook, [*steps, transfer, *more_steps]


def _run(
    playbook: str, handoff: Handoff, request_id: str, context: Context
) -> tuple[Worked, list[dict]]:
    working = dataclasses.replace(context, request_id=request_id, playbook=playbook)
    worked, step = _traced(
        f"department:{playbook}", lambda: department.run(handoff, working), _worked_text
    )

    return worked, [*worked.steps, step]


# The model that decided the request names its concerns: the chief of staff when it sent the
# message to a person, the department agent when it filed a proposal.
def _concerns(
    routed: chief_of_staff.Routed | chief_of_staff.Person, filed: proposal.Proposal | None
) -> list[str]:
    if isinstance(routed, chief_of_staff.Person):
        return routed.concerns

    return [] if filed is None else filed.concerns


def _worked_text(worked: Worked) -> str:
    if worked.proposal is None:
        return f"held: {worked.held_reason}"

    return f"proposal: {worked.proposal.kind}"


def _routed_text(routed: chief_of_staff.Routed | chief_of_staff.Person) -> str:
    if isinstance(routed, chief_of_staff.Person):
        return f"person: {routed.reason}"

    return routed.playbook


def _checks_text(checks: dict) -> str:
    return ", ".join(f"{check} {_check_text(result)}" for check, result in checks.items())


def _check_text(result: verifier.Check) -> str:
    return "pass" if result is None else f"fail: {result}"
