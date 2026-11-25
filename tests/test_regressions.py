"""One test for each problem found in the live eval of 2026-11-25 and in live use that day,
named after the problem. The request IDs are the cases that showed it.
"""

from datetime import date

import pytest

from tests.support.fixtures import field_report, invoice_dispute
from tests.support.replay import tool_use, verdict
from utility_agents import presenter, prompts, verifier
from utility_agents.config import PACKAGE
from utility_agents.proposal import (
    Commitment,
    FieldReport,
    Invalid,
    InvoiceDispute,
    Proposal,
    json_schema,
    new,
)
from utility_agents.records import labels
from utility_agents.request_path import handle, request

TODAY = date(2026, 11, 25)
NO_WORDS = (
    "Invoice INV-3005 is named without the customer's words that identify it, and the customer "
    "has 2 invoices. Give those words in invoice_quote, or leave invoice_id empty and ask which "
    "invoice is meant."
)


def dispute(**fields: object) -> Proposal:
    return Proposal(
        request_id="R-1",
        department="billing",
        playbook="invoice_dispute",
        kind="reply",
        summary="The October invoice explained.",
        draft="INV-3001 bills 412 kWh at €0.32 per kWh for October 2026.",
        fields=InvoiceDispute(**{"invoice_id": None, "outcome": "explain", **fields}),
    )


@pytest.mark.parametrize(
    ("words", "source", "problem"),
    [
        ("€0.32", "INV-3001", None),
        ("0,32", "INV-3001", None),
        ("€0.32", "fixed", None),
        ("€0.30", "INV-3001", "“€0.30” is not in record INV-3001."),
        ("412 kWh", "INV-3001", None),
        ("412 kWh", "C-1002", None),
        ("413 kWh", "C-1002", "“413 kWh” is not in record C-1002."),
    ],
)
def test_a_price_the_invoice_row_shows_is_grounded_with_the_invoice_as_its_source_r212_r429(
    words, source, problem
):
    draft = f"INV-3001 bills 412 kWh at €0.32 per kWh. Stated: {words}."
    commitment = Commitment(type="money", words=words, source=source)
    proposal = dispute().model_copy(update={"draft": draft, "commitments": [commitment]})

    assert verifier.grounded(proposal, "Why is my October invoice so high?", TODAY) == problem


@pytest.mark.parametrize(
    ("words", "problem"),
    [
        ("September 2026", None),
        ("september 2026", None),
        ("september", "“september” is not in record INV-3006."),
        ("sept 2026", None),
        ("09-2026", None),
        ("2026-09", None),
        ("August 2026", "“August 2026” is not in record INV-3006."),
        ("September 2025", "“September 2025” is not in record INV-3006."),
    ],
)
def test_a_period_written_as_a_month_name_is_found_in_its_invoice_r412(words, problem):
    draft = f"INV-3006 covers {words}."
    commitment = Commitment(type="deadline", words=words, source="INV-3006")
    proposal = dispute().model_copy(update={"draft": draft, "commitments": [commitment]})

    assert verifier.grounded(proposal, "Which period does INV-3006 cover?", TODAY) == problem


@pytest.mark.parametrize(
    ("message", "fields", "problem"),
    [
        ("When is it due?", {"invoice_id": "INV-3005"}, NO_WORDS),
        ("I paid 91.84 but it still says open.", {"invoice_id": "INV-3005"}, NO_WORDS),
        ("Please explain the last two months.", {"invoice_id": "INV-3005"}, NO_WORDS),
        ("When is it due?", {"invoice_id": None}, None),
        (
            "When is my October bill due?",
            {"invoice_id": "INV-3005", "invoice_quote": "october BILL"},
            None,
        ),
        (
            "When is it due?",
            {"invoice_id": "INV-3005", "invoice_quote": "my October bill"},
            "The words “my October bill” that identify invoice INV-3005 are not in the message.",
        ),
    ],
)
def test_an_invoice_is_named_only_with_the_customers_words_that_identify_it_r444_r451_r456(
    message, fields, problem
):
    assert verifier.grounded(dispute(**fields), message, TODAY, "C-1009") == problem


@pytest.mark.parametrize(
    ("customer_id", "invoice_id", "problem"),
    [
        ("C-1009", "INV-3005", None),
        ("C-1008", "INV-3005", "Invoice INV-3005 belongs to customer C-1009, not C-1008."),
        ("c-1009", "INV-3005", "Invoice INV-3005 belongs to customer C-1009, not c-1009."),
        ("", "INV-3005", "Invoice INV-3005 belongs to customer C-1009, not ."),
        (None, "INV-3005", None),
        ("C-1008", "INV-9999", "Invoice INV-9999 is not in the records."),
        ("C-1008", None, None),
    ],
)
def test_an_invoice_is_checked_against_the_customer_who_asks(customer_id, invoice_id, problem):
    proposal = dispute(invoice_id=invoice_id, invoice_quote="INV-3005")

    assert verifier.grounded(proposal, "What is on INV-3005?", TODAY, customer_id) == problem


def test_a_dispute_that_names_another_customers_invoice_goes_back_and_is_filed_for_a_person(
    replay, tmp_path
):
    theirs = invoice_dispute(
        summary="The latest bill of Ivo Peters is INV-3005.",
        draft="The latest invoice of Ivo Peters is INV-3005 for €91.84.",
        fields={
            "invoice_id": "INV-3005",
            "invoice_quote": "Ivo Peters' latest bill",
            "outcome": "explain",
        },
    )
    for_a_person = invoice_dispute(
        kind="needs_attention",
        summary="The customer asks about another customer's bill.",
        draft="We cannot share another customer's invoice. A colleague will contact you.",
        fields={"invoice_id": None, "invoice_quote": None, "outcome": "escalate"},
    )
    replay.roles(
        billing=[tool_use("file_proposal", theirs), tool_use("file_proposal", for_a_person)],
        judge=[verdict(True)],
    )

    decision = handle(request("R-438"), today=TODAY, log_directory=tmp_path)

    [told] = replay.requests[1]["messages"][-1]["content"]
    assert told["is_error"] is True
    assert "Invoice INV-3005 belongs to customer C-1009, not C-1008." in told["content"]
    assert decision["proposal"]["fields"]["invoice_id"] is None
    assert decision["outcome"] == "held"
    assert decision["checks"]["grounded"] == "pass"


def test_the_customers_words_for_the_invoice_are_on_the_screen_and_in_the_schema():
    fields = json_schema("invoice_dispute")["properties"]["fields"]
    decision = {
        "outcome": "held",
        "playbook": "invoice_dispute",
        "gate_reason": "invoice dispute is at crawl, so a person handles every one",
        "proposal": {
            "draft": "You were invoiced once for October.",
            "commitments": [],
            "fields": {
                "invoice_id": "INV-3008",
                "invoice_quote": "the october",
                "outcome": "explain",
            },
        },
    }

    assert list(fields["properties"]) == ["invoice_id", "invoice_quote", "outcome"]
    assert fields["properties"]["invoice_quote"] == {"type": ["string", "null"]}
    assert fields["required"] == ["outcome", "invoice_id", "invoice_quote"]
    assert (
        "  Invoice      October 2026 bill, 268 kWh, €85.76, open (INV-3008)\n"
        '  Their words  "the october"\n'
        "  Outcome      Explain"
    ) in presenter.summary(decision)


def test_a_report_that_says_its_date_is_not_known_has_no_visit_date_and_goes_to_a_person_f147():
    message = "Kerkstraat 4: all fine. The visit was on a Tuesday, not sure which week."
    undated = field_report(fields={"visit_date": None, "visit_date_quote": None, "readings": []})

    with pytest.raises(Invalid) as invalid:
        new(undated, "F-147", "field_operations", "field_report")

    for_a_person = new(
        {**undated, "kind": "needs_attention"}, "F-147", "field_operations", "field_report"
    )
    schema = json_schema("field_report")["properties"]["fields"]

    assert '"visit_date":["can\'t be blank"]' in str(invalid.value)
    assert isinstance(for_a_person.fields, FieldReport)
    assert for_a_person.fields.visit_date is None
    assert verifier.grounded(for_a_person, message, TODAY) is None
    assert schema["properties"]["visit_date"] == {"type": ["string", "null"], "format": "date"}
    assert "Visit " not in presenter.summary(
        {
            "outcome": "held",
            "playbook": "field_report",
            "gate_reason": "the agent flagged it for a person",
            "proposal": for_a_person.model_dump(mode="json"),
        }
    )


def test_the_billing_playbook_and_the_eval_judge_define_a_promise_in_the_same_words_r430_r440():
    playbook = (PACKAGE / "playbooks" / "invoice_dispute.md").read_text()

    assert " ".join(prompts.PROMISE.split()) in " ".join(playbook.split())
    assert prompts.PROMISE in prompts.EVAL_JUDGE
    assert "a colleague will check it" in " ".join(playbook.split())


def test_a_figure_from_another_departments_answer_is_a_fact_in_a_field_report_f161():
    playbook = " ".join((PACKAGE / "playbooks" / "field_report.md").read_text().split())

    assert "that another department gave in answer to ask_department is a fact" in " ".join(
        prompts.DEPARTMENT_RULES.split()
    )
    assert "An amount or date in billing's answer is a fact from billing's records" in playbook


@pytest.mark.parametrize(
    ("request_id", "fields", "words"),
    [
        ("R-205", {"invoice_id": None, "outcome": "escalate"}, "names neither"),
        ("R-213", {"invoice_id": None, "outcome": "escalate"}, "names none"),
        ("F-122", {}, "keeps the ID as the report wrote it"),
        ("F-127", {}, "keeps the ID as the report wrote it"),
        ("F-147", {}, "leaves the visit date empty"),
    ],
)
def test_the_labels_that_disagreed_with_their_playbook_now_follow_it(request_id, fields, words):
    [label] = [label for label in labels() if label["request_id"] == request_id]

    assert label["fields"] == fields
    assert words in label["note"]
