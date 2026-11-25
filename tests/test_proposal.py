import json
from datetime import date
from typing import get_origin

import pytest

from tests.support.fixtures import invoice_dispute
from utility_agents.proposal import (
    PLAYBOOKS,
    FieldReport,
    Invalid,
    InvoiceDispute,
    PolicyQuestion,
    json_schema,
    new,
)

CONTEXT = ("F-001", "field_operations", "field_report")
VALID = {
    "summary": "Comms module reset.",
    "draft": "Meter A-2001 was not communicating. Reset the comms module.",
    "commitments": [],
    "kind": "record_update",
    "fields": {
        "customer_id": "C-1001",
        "asset_id": "A-2001",
        "visit_date": "2026-11-18",
        "fault_type": "meter_fault",
        "follow_up": "none",
        "billing_follow_up": "none",
        "visit_date_quote": "on 18 Nov",
        "readings": [{"value": 14_502, "unit": "kwh", "quote": "Reading 14,502 kWh"}],
    },
}
PREFIX = "The proposal is invalid: "


def test_the_file_proposal_schema_for_every_playbook_lists_exactly_the_ecto_fields():
    for playbook, model in [
        ("invoice_dispute", InvoiceDispute),
        ("field_report", FieldReport),
        ("policy_question", PolicyQuestion),
    ]:
        schema = json_schema(playbook)
        properties = schema["properties"]
        fields = properties["fields"]

        handed_over = [] if playbook == "field_report" else ["transfer_to"]

        assert list(properties) == [
            "fields",
            "summary",
            "draft",
            "unconfirmed",
            "commitments",
            "concerns",
            "kind",
            *handed_over,
        ]

        assert schema["required"] == [
            "fields",
            "unconfirmed",
            "concerns",
            "commitments",
            "summary",
            "draft",
            "kind",
        ]

        assert properties["commitments"]["type"] == "array"
        assert properties["commitments"]["items"]["required"] == ["type", "words", "source"]

        declared = model.model_fields
        required = [name for name, field in declared.items() if field.is_required()]
        embeds = [name for name, field in declared.items() if get_origin(field.annotation) is list]
        nullable = [name for name in declared if name not in required + embeds]

        assert list(fields["properties"]) == list(declared)
        assert fields["required"] == required + nullable

        for field in nullable:
            nullable_type = fields["properties"][field]["type"]
            assert isinstance(nullable_type, list)
            assert len(nullable_type) == 2
            assert nullable_type[1] == "null"

    assert sorted(PLAYBOOKS) == ["field_report", "invoice_dispute", "policy_question"]


def test_valid_input_becomes_a_proposal_with_the_codes_request_department_and_playbook():
    filed = {**VALID, "request_id": "X-1", "department": "hr"}

    proposal = new(filed, *CONTEXT)

    assert proposal.request_id == "F-001"
    assert proposal.department == "field_operations"
    assert proposal.kind == "record_update"

    assert proposal.fields.visit_date == date(2026, 11, 18)

    [reading] = proposal.fields.readings
    assert (reading.value, reading.unit, reading.quote) == (14_502.0, "kwh", "Reading 14,502 kWh")

    commitment = {"type": "deadline", "words": "30 November", "source": "INV-3001"}
    [committed] = new({**VALID, "commitments": [commitment]}, *CONTEXT).commitments
    assert (committed.type, committed.words, committed.source) == (
        "deadline",
        "30 November",
        "INV-3001",
    )


def test_a_field_report_is_never_handed_over_and_no_department_hands_a_request_to_itself():
    assert "transfer_to" not in json_schema("field_report")["properties"]

    assert new({**VALID, "transfer_to": "billing"}, *CONTEXT).transfer_to is None

    dispute = invoice_dispute(
        summary="The October invoice is an estimate.",
        draft="A colleague will check your October invoice.",
    )

    for target, error in [("billing", "is this department"), ("field_operations", "is invalid")]:
        message = invalid_message({**dispute, "transfer_to": target}, "R-201", "billing")

        assert f'"transfer_to":["{error}"]' in message


def test_a_crm_update_must_name_its_customer_and_asset_a_report_for_a_person_may_leave_them_out():
    unnamed = {**VALID, "fields": {**VALID["fields"], "customer_id": None}}

    assert '"customer_id":["can\'t be blank"]' in invalid_message(unnamed)

    assert new({**unnamed, "kind": "needs_attention"}, *CONTEXT).kind == "needs_attention"


def test_each_playbook_accepts_only_its_own_kinds_of_proposal():
    for playbook, kinds in [
        ("field_report", ["record_update", "needs_attention"]),
        ("invoice_dispute", ["reply", "needs_attention"]),
        ("policy_question", ["reply", "needs_attention"]),
    ]:
        assert json_schema(playbook)["properties"]["kind"]["enum"] == kinds

    assert '"kind":["is invalid"]' in invalid_message({**VALID, "kind": "reply"})


def test_a_placeholder_summary_or_draft_goes_back_to_the_agent_as_invalid():
    problems = json.loads(invalid_message({**VALID, "summary": "x", "draft": "x"}))

    assert problems["summary"] == ["should be at least 10 character(s)"]
    assert problems["draft"] == ["should be at least 20 character(s)"]


def test_every_invalid_field_shared_or_playbook_is_named_in_one_message():
    fields = {name: value for name, value in VALID["fields"].items() if name != "fault_type"}
    filed = {
        **VALID,
        "kind": "send",
        "commitments": [{"type": "refund", "words": "€5", "source": "message"}],
        "fields": {**fields, "readings": [{"value": 1, "quote": "1 kWh"}]},
    }

    assert json.loads(invalid_message(filed)) == {
        "commitments": [{"type": ["is invalid"]}],
        "kind": ["is invalid"],
        "fields": {
            "fault_type": ["can't be blank"],
            "readings": [{"unit": ["can't be blank"]}],
        },
    }


def invalid_message(
    filed: dict, request_id: str = "F-001", department: str = "field_operations"
) -> str:
    """The problems text of an invalid proposal, after its fixed opening."""
    playbook = "field_report" if department == "field_operations" else "invoice_dispute"

    with pytest.raises(Invalid) as invalid:
        new(filed, request_id, department, playbook)

    text = str(invalid.value)
    assert text.startswith(PREFIX)

    return text.removeprefix(PREFIX)
