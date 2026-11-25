"""What the system sends to the API and shows to people, compared with a recording.

`WRITE_GOLDEN=1` records `golden/golden.json` again, only after a change meant to alter what is
sent.
"""

import json
import os
from datetime import date
from functools import partial
from pathlib import Path

from tests.support.fixtures import TODAY, working
from tests.support.replay import text
from utility_agents import (
    chief_of_staff,
    department,
    evaluation,
    flags,
    judge,
    notifications,
    presenter,
    verifier,
)
from utility_agents.config import settings
from utility_agents.proposal import PLAYBOOKS, Commitment, FieldReport, PolicyQuestion, Proposal
from utility_agents.work import Context, Handoff, Request

PATH = Path(__file__).parent / "golden" / "golden.json"
JUDGE = "claude-haiku-5-5"
MESSAGE = (
    "Kerkstraat 4, C-1002, meter A-2002. Loose neutral tightened. Reading 9,876 kWh, 19-11-2026."
)
REFUSED = (400, {"error": "golden"})
UNREADABLE = (200, text("no json"))
REPORT = Proposal(
    request_id="G-1",
    department="field_operations",
    playbook="field_report",
    kind="record_update",
    summary="Loose neutral tightened.",
    draft="Loose neutral at the meter connection tightened.",
    commitments=[],
    concerns=["safety"],
    fields=FieldReport(
        customer_id="C-1002",
        asset_id="A-2002",
        visit_date=date(2026, 11, 19),
        visit_date_quote="19-11-2026",
        fault_type="connection_fault",
        follow_up="revisit",
        billing_follow_up="meter_accuracy",
        readings=[],
    ),
)


def test_what_the_system_sends_and_shows_matches_the_recorded_golden_file(replay):
    if os.environ.get("WRITE_GOLDEN") == "1":
        PATH.write_text(json.dumps(golden(replay), indent=2, ensure_ascii=False, sort_keys=True))

    recorded = json.loads(PATH.read_text())
    actual = golden(replay)

    assert sorted(actual) == sorted(recorded)

    for name, value in recorded.items():
        if name.startswith("request: "):
            assert canonical(value) == value, f"{name}: the canonical form changes the recording"

        assert actual[name] == value, f"{name} differs from the golden file"


def golden(replay) -> dict:
    return {**requests(replay), **outputs()}


def requests(replay) -> dict:
    sent = {}

    for playbook in PLAYBOOKS:
        request, _answered = exchange(replay, REFUSED, partial(work, playbook))
        sent[f"request: {playbook}"] = request

    for name, call in (("sense", sense), ("eval judge", grade), ("chief of staff", route)):
        for response, outcome in ((REFUSED, "failed"), (UNREADABLE, "unreadable")):
            request, answered = exchange(replay, response, call)
            sent[f"{outcome}: {name}"] = shown(answered)

            if outcome == "failed":
                sent[f"request: {name}"] = request

    return sent


def outputs() -> dict:
    return {
        "flags and notifications": flags_and_notifications(),
        "presenter": presenter.describe(decision(), entries()),
        "eval report": evaluation.report(evaluation.Run("policy_question", results())),
    }


def exchange(replay, response, call) -> tuple[str, object]:
    """The request sent, in a fixed form, and what the call returned."""
    replay.always(*response)
    answered = call()

    return canonical(replay.raw[-1]), answered


def canonical(body: str) -> str:
    """Plain objects are written in an order the API ignores, so their keys are sorted. A
    schema's "properties" keep their order, because the model fills the fields in that order."""
    return json.dumps(ordered(json.loads(body)), separators=(",", ":"), ensure_ascii=False)


def ordered(value: object, key: str | None = None) -> object:
    if isinstance(value, dict) and key == "properties":
        return {name: ordered(item) for name, item in value.items()}

    if isinstance(value, dict):
        return {name: ordered(item, name) for name, item in sorted(value.items())}

    if isinstance(value, list):
        return [ordered(item) for item in value]

    if isinstance(value, str):
        return embedded(value)

    return value


def embedded(text: str) -> str:
    """A proposal is embedded in a prompt as JSON text, whose key order can change the same
    way."""
    before, opening, rest = text.partition("<proposal>\n")

    if not opening:
        return text

    proposal, closing, after = rest.partition("\n</proposal>")

    return before + opening + canonical(proposal) + closing + after


def shown(answered: object) -> object:
    """A result as the recording holds it: a check's failure text, or for the front door the
    reason a person gets the request and the concerns it raised."""
    if isinstance(answered, chief_of_staff.Person):
        return {"reason": answered.reason, "concerns": answered.concerns}

    return answered


def work(playbook: str):
    return department.run(handoff(), working(playbook, "G-1"))


def handoff() -> Handoff:
    return Handoff(message=MESSAGE, intent="field report", tried="nothing yet", customer_id=None)


def route():
    request = Request(id="G-2", channel="email", customer_id="C-1001", message="My bill is wrong.")

    return chief_of_staff.route(request, Context(today=TODAY, models=settings["models"]))


def sense():
    return verifier.sense(REPORT, MESSAGE, JUDGE, TODAY)


def grade():
    label = {
        "kind": "record_update",
        "fields": {"customer_id": "C-1002", "fault_type": "connection_fault"},
        "note": "A golden note.",
    }
    held = {"outcome": "held", "proposal": {"summary": "Loose neutral tightened."}}

    return judge.verdict(label, held, MESSAGE, JUDGE)


def flags_and_notifications() -> list[dict]:
    answer = REPORT.model_copy(
        update={"playbook": "policy_question", "fields": PolicyQuestion(policy_id="P-01")}
    )

    return [
        {
            "concern": concern,
            "playbook": proposal.playbook,
            "labels": [flag.label for flag in raised],
            "notifications": notifications.build("G-1", raised, proposal),
        }
        for concern in flags.CONCERNS
        for proposal in (REPORT, answer)
        for raised in [flags.raised([concern], "email", None)]
    ]


def decision() -> dict:
    commitment = Commitment(type="deadline", words="30 November", source="INV-3005")
    reply = REPORT.model_copy(
        update={
            "playbook": "invoice_dispute",
            "kind": "reply",
            "commitments": [commitment],
            "unconfirmed": "Whether the meter was read.",
        }
    )

    return {
        "request_id": "G-3",
        "playbook": "invoice_dispute",
        "outcome": "held",
        "gate_reason": "invoice dispute is at crawl, so a person handles every one",
        "checks": {"format": "pass", "grounded": "pass", "sense": "fail: Wrong invoice."},
        "flags": ["money asked for or promised"],
        "notifications": [{"to": "Billing", "text": "A golden notification."}],
        "usage": {"cost_usd": 0.0123},
        "proposal": {
            **reply.model_dump(mode="json"),
            "fields": {"invoice_id": "INV-3005", "outcome": "escalate"},
        },
    }


def entries() -> list[dict]:
    return [
        {"step": "chief_of_staff", "result": "invoice_dispute", "milliseconds": 1500},
        {"step": "department:invoice_dispute", "result": "proposal", "milliseconds": 9000},
    ]


def results() -> list[evaluation.Result]:
    passed = {"request_id": "R-301", "kind": "reply", "fields": {}, "flags": []}
    ambiguous = {**passed, "request_id": "R-541", "category": "ambiguous"}
    acted = {"outcome": "automatic"}

    return [
        evaluation.Result(passed, 1, acted, None, 0.01),
        evaluation.Result(ambiguous, 1, acted, "the judge disagrees: It guessed.", 0.02),
    ]
