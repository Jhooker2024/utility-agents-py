"""What a department agent files: the shared fields plus `fields`, the playbook's own model
picked from `PLAYBOOKS`. The agent fills everything except `request_id`, `department` and
`playbook`, which the code sets. Only departments that take people's messages can receive a
transfer; field operations takes technicians' reports.

`json_schema` generates the `file_proposal` input schema from these models, so the tool and the
validation cannot drift apart. `new` validates the agent's input and returns the proposal, or
raises `Invalid` with every problem as one message the agent can act on.
"""

import json
from datetime import date
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field, ValidationError, field_validator

from utility_agents import flags, records, schema

Department = Literal["billing", "field_operations", "hr"]
Kind = Literal["reply", "record_update", "needs_attention"]
TransferTarget = Literal["billing", "hr"]

REQUIRED = ["summary", "draft", "kind"]
MIN_SUMMARY = 10
MIN_DRAFT = 20
BLANK = "can't be blank"
INVALID = "is invalid"


class Invalid(ValueError):
    """The agent's input is not a valid proposal; the text lists every invalid field."""


class Entry(BaseModel):
    """What every model the agent fills shares: text of only spaces is no value."""

    @field_validator("*", mode="before")
    @classmethod
    def empty_is_missing(cls, value: object) -> object:
        if _blank(value):
            return None

        return value


class Commitment(Entry):
    """One promise in a draft: its type, the words as the draft writes them, and where it
    comes from: `message`, or the ID of the record that holds it. `verifier` checks the words
    against the draft and the source."""

    type: Literal["money", "deadline", "legal"]
    words: str
    source: str


class Reading(Entry):
    value: float
    unit: Literal["kwh", "volt"]
    quote: str


class FieldReport(Entry):
    customer_id: str | None = None
    asset_id: str | None = None
    visit_date: date | None = None
    visit_date_quote: str | None = None
    fault_type: Literal[
        "no_fault", "meter_fault", "cable_damage", "connection_fault", "tampering", "other"
    ]
    follow_up: Literal["none", "revisit", "replace_asset", "escalate"]
    follow_up_date: date | None = None
    billing_follow_up: Literal["none", "tampering", "meter_accuracy", "meter_replaced"]
    readings: list[Reading] = []


class InvoiceDispute(Entry):
    invoice_id: str | None = None
    invoice_quote: str | None = None
    outcome: Literal["explain", "correct", "escalate"]


class PolicyQuestion(Entry):
    policy_id: str | None = None


class Shared(Entry):
    """The fields every playbook's proposal has, in the order the agent fills them."""

    summary: str = Field(min_length=MIN_SUMMARY)
    draft: str = Field(min_length=MIN_DRAFT)
    unconfirmed: str | None = None
    commitments: list[Commitment] = []
    concerns: list[flags.ConcernName] = []
    kind: Kind
    transfer_to: TransferTarget | None = None


class Proposal(Shared):
    request_id: str
    department: Department
    playbook: str
    fields: FieldReport | InvoiceDispute | PolicyQuestion


class Playbook(NamedTuple):
    """A playbook's department, its fields and the kinds a proposal for it may have."""

    department: str
    fields: type[Entry]
    kinds: tuple[str, ...]


PLAYBOOKS = {
    "field_report": Playbook("field_operations", FieldReport, ("record_update", "needs_attention")),
    "invoice_dispute": Playbook("billing", InvoiceDispute, ("reply", "needs_attention")),
    "policy_question": Playbook("hr", PolicyQuestion, ("reply", "needs_attention")),
}
DEPARTMENTS = ("billing", "field_operations", "hr")
KINDS = ("reply", "record_update", "needs_attention")
# A record update must say what it updates and when; a proposal for a person may leave them
# open.
NEEDED_TO_UPDATE = {("field_report", "record_update"): (*records.REPORT_FIELDS, "visit_date")}
# A field report is never handed over: what billing needs goes in its billing follow-up, so
# the CRM update is never lost to another department's proposal.
NEVER_HANDED_OVER = ("field_report",)


def department(playbook: str) -> str:
    """The department that owns a playbook."""
    return PLAYBOOKS[playbook].department


def request_playbook(department: str) -> str:
    """The playbook a department works a request with."""
    return next(name for name, entry in PLAYBOOKS.items() if entry.department == department)


def json_schema(playbook: str) -> dict:
    """The `file_proposal` input schema for a playbook, playbook fields first."""
    entry = PLAYBOOKS[playbook]
    properties = {
        "fields": schema.model_object(entry.fields),
        **schema.properties(Shared),
        "kind": {"type": "string", "enum": list(entry.kinds)},
    }

    if playbook in NEVER_HANDED_OVER:
        del properties["transfer_to"]

    return schema.strict_object(
        properties, ["fields", "unconfirmed", "concerns", "commitments", *REQUIRED]
    )


def new(filed: dict, request_id: str, department: str, playbook: str) -> Proposal:
    """The proposal the agent filed, or `Invalid` listing every invalid field."""
    entry = PLAYBOOKS[playbook]
    kind = filed.get("kind")
    shared_input = {name: value for name, value in filed.items() if name in Shared.model_fields}
    fields_input = filed.get("fields") if isinstance(filed.get("fields"), dict) else {}

    if playbook in NEVER_HANDED_OVER:
        shared_input.pop("transfer_to", None)

    shared, problems = _validated(Shared, shared_input)
    fields, field_problems = _validated(entry.fields, fields_input)

    if "kind" not in problems and kind not in entry.kinds:
        problems["kind"] = [INVALID]

    if shared_input.get("transfer_to") == department:
        problems["transfer_to"] = ["is this department"]

    for name in NEEDED_TO_UPDATE.get((playbook, kind), ()):
        if _blank(fields_input.get(name)):
            field_problems.setdefault(name, [BLANK])

    if field_problems:
        problems["fields"] = field_problems

    if problems:
        listed = json.dumps(problems, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        raise Invalid("The proposal is invalid: " + listed)

    return Proposal(
        request_id=request_id,
        department=department,
        playbook=playbook,
        fields=fields,
        **dict(shared),
    )


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _validated(model: type[Entry], filed: dict) -> tuple[Entry | None, dict]:
    try:
        return model.model_validate(filed), {}
    except ValidationError as error:
        return None, _problems(error, filed)


# Problems by field, in the words the agent is told. A list of entries, such as the readings,
# gets one item per entry, empty for an entry with no problem.
def _problems(error: ValidationError, filed: dict) -> dict:
    problems: dict = {}

    for issue in error.errors():
        field, *rest = issue["loc"]

        if len(rest) == 2:
            index, name = rest
            entries = problems.setdefault(field, [{} for _entry in filed[field]])
            entries[index][name] = [_problem(issue)]
        else:
            problems[field] = [_problem(issue)]

    return problems


def _problem(issue: dict) -> str:
    if issue["type"] == "missing" or (issue["input"] is None and issue["type"] != "list_type"):
        return BLANK

    if issue["type"] == "string_too_short":
        return f"should be at least {issue['ctx']['min_length']} character(s)"

    return INVALID
