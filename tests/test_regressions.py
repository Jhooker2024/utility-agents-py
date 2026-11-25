"""One test for each problem found in live use, named after the problem. The request IDs are
the labelled cases that showed it.
"""

import os
from datetime import date

import pytest

from tests.support.fixtures import field_report, hr_answer, invoice_dispute, working
from tests.support.replay import end_turn, grade, role, route, tool_use, verdict
from utility_agents import (
    cli,
    department,
    evaluation,
    flags,
    gate,
    judge,
    presenter,
    prompts,
    verifier,
)
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
from utility_agents.work import Handoff

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


def test_the_billing_agent_and_the_eval_judge_are_sent_one_definition_of_a_promise_r430_r440(
    replay,
):
    replay.always(400, {"error": "refused"})
    asked = Handoff("Will you pay compensation?", "invoice dispute", "nothing yet", "C-1005")

    department.run(asked, working("invoice_dispute", "R-440"))
    judge.verdict({"kind": "needs_attention", "fields": {}}, {"outcome": "held"}, "m", "m")

    billing, grader = (" ".join(sent["system"][0]["text"].split()) for sent in replay.requests)
    promise = " ".join(prompts.PROMISE.split())

    assert promise.startswith("A promise tells the reader that something will happen")
    assert "is a promise when no record shows that" in promise
    assert promise in billing
    assert promise in grader
    assert "for anything the records cannot settle, say a colleague will check it" in billing


def test_a_figure_from_billings_answer_stays_in_a_field_note_and_is_no_commitment_f161(
    replay, tmp_path
):
    note = "Meter fine. Billing says the October invoice of €91.84 is open, due 30 Nov 2026."
    filed = field_report(
        draft=note,
        fields={
            "customer_id": "C-1009",
            "asset_id": "A-2009",
            "visit_date": "2026-11-24",
            "visit_date_quote": "24 Nov",
            "fault_type": "no_fault",
            "follow_up": "none",
            "readings": [{"value": 31560, "unit": "kwh", "quote": "reading 31,560 kWh"}],
        },
    )
    listed = {**filed, "commitments": [{"type": "money", "words": "€91.84", "source": "INV-3005"}]}
    question = {"department": "billing", "question": "Is the October invoice of C-1009 paid?"}
    replay.roles(
        field_operations=[
            tool_use("ask_department", question),
            tool_use("file_proposal", listed),
            tool_use("file_proposal", filed),
        ],
        billing=[end_turn("INV-3005 for October 2026 is open: €91.84, due 30 Nov 2026.")],
        judge=[verdict(True)],
    )

    decision = handle(request("F-161"), today=date(2026, 11, 24), log_directory=tmp_path)

    first, _consult, _second, third, _judge = replay.requests
    rules = " ".join(first["system"][0]["text"].split())
    [told] = third["messages"][-1]["content"]

    assert "that another department gave in answer to ask_department is a fact" in rules
    assert "An amount or date in billing's answer is a fact from billing's records" in rules
    assert told["is_error"] is True
    assert (
        "The note lists a commitment (€91.84), and a field report promises nothing."
        in (told["content"])
    )
    assert decision["proposal"]["draft"] == note
    assert decision["proposal"]["commitments"] == []
    assert decision["checks"]["grounded"] == "pass"
    assert decision["outcome"] == "automatic"


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


READ = tool_use("get_record", {"collection": "assets", "id": "A-2002"})


def test_a_proposal_filed_on_the_last_allowed_model_request_is_kept(replay):
    report = field_report(draft="Loose neutral at meter A-2002 tightened.", fields={"readings": []})
    replay.sequence([READ] * (department.MAX_TURNS - 1) + [tool_use("file_proposal", report)])

    worked = department.run(REPORTED, working("field_report", "F-1"))

    assert department.MAX_TURNS == 8
    assert len(replay.requests) == 8
    assert worked.held_reason is None
    assert worked.proposal.fields.customer_id == "C-1002"


def test_a_nudged_reply_counts_as_one_of_the_eight_model_requests(replay):
    replies = iter([end_turn("Done.")])
    replay.respond(lambda _body: (200, next(replies, READ)))

    worked = department.run(REPORTED, working("field_report", "F-1"))

    assert worked.held_reason == "No proposal after 8 model requests."
    assert len(replay.requests) == 8
    assert replay.requests[1]["messages"][-1] == {"role": "user", "content": department.NUDGE}


REPORTED = Handoff(
    message="Kerkstraat 4, C-1002, meter A-2002. Loose neutral, tightened. 19-11-2026.",
    intent="field report",
    tried="nothing yet",
    customer_id=None,
)


def report(**fields: object) -> Proposal:
    """A field report for C-1002 and A-2002, visited today, with `fields` replaced."""
    dated = {"visit_date": TODAY.isoformat(), "visit_date_quote": None, "readings": [], **fields}

    return new(field_report(fields=dated), "F-1", "field_operations", "field_report")


@pytest.mark.parametrize(
    ("message", "value", "quote", "problem"),
    [
        ("C-1002, A-2002. Reading 9,876 kWh.", 9876, "Reading 9,876 kWh", None),
        ("C-1002, A-2002. Reading 14 502 kWh.", 14502, "Reading 14 502 kWh", None),
        ("C-1002, A-2002. Reading 9,876 kWh.", 987, "Reading 9,876 kWh", "Reading 987"),
        ("C-1002, A-2002. Reading 9,876 kWh.", 876, "Reading 9,876 kWh", "Reading 876"),
        ("C-1002, A-2002. Reading 9,876 kWh.", 98.76, "Reading 9,876 kWh", "Reading 98.76"),
        ("C-1002, A-2002. Meter 12 read 34 kWh.", 1234, "Meter 12 read 34 kWh", "Reading 1234"),
    ],
)
def test_a_reading_whose_digits_only_sit_inside_the_quoted_number_fails_the_fact_check(
    message, value, quote, problem
):
    filed = report(readings=[{"value": value, "unit": "kwh", "quote": quote}])
    expected = problem and f"{problem} is not in the report as quoted."

    assert verifier.grounded(filed, message, TODAY) == expected


@pytest.mark.parametrize(
    ("visit_date", "quote", "problem"),
    [
        ("2026-11-19", "19 Nov", None),
        ("2026-11-19", "19-11-2026", None),
        ("2024-11-19", "19 Nov", "Visit date 19 Nov 2024 is not in the report as quoted."),
        ("2024-11-19", "19-11-2026", "Visit date 19 Nov 2024 is not in the report as quoted."),
        ("2026-11-19", "19 Nov 2024", "Visit date 19 Nov 2026 is not in the report as quoted."),
    ],
)
def test_a_visit_date_in_another_year_than_the_report_gives_fails_the_fact_check(
    visit_date, quote, problem
):
    message = f"C-1002, A-2002. Loose neutral tightened, {quote}."
    filed = report(visit_date=visit_date, visit_date_quote=quote)

    assert verifier.grounded(filed, message, TODAY) == problem


@pytest.mark.parametrize(
    ("kind", "words", "problem"),
    [
        ("money", "€396.80 on INV-3002", None),
        ("deadline", "30 Nov 2026", None),
        ("money", "€500 on INV-3002", "is not in record INV-3002."),
        ("money", "€396.80 and €500 back", "holds a figure that is not in record INV-3002."),
        (
            "money",
            "a €50 credit for October 2026",
            "holds a figure that is not in record INV-3002.",
        ),
        ("deadline", "30 Nov 2027", "holds a figure that is not in record INV-3002."),
        ("money", "a refund on INV-3002", "is not in record INV-3002."),
    ],
)
def test_a_commitment_that_only_names_its_record_or_adds_a_figure_fails_the_fact_check(
    kind, words, problem
):
    commitment = Commitment(type=kind, words=words, source="INV-3002")
    filed = dispute(invoice_id="INV-3002", invoice_quote="INV-3002").model_copy(
        update={"draft": f"About your bill: {words}.", "commitments": [commitment]}
    )
    expected = problem and f"“{words}” {problem}"

    assert verifier.grounded(filed, "My bill INV-3002 is wrong.", TODAY, "C-1005") == expected


def test_concerns_filed_before_a_hand_over_still_raise_their_flags_and_tell_their_teams(
    replay, tmp_path
):
    handed_on = invoice_dispute(
        summary="A threat in a question about leave, not a bill.",
        kind="needs_attention",
        concerns=["legal", "vulnerable"],
        fields={"invoice_id": None, "outcome": "escalate"},
    )
    answer = hr_answer(
        summary="Leave carry-over answered from P-01.",
        draft="Up to 5 unused leave days carry over to next year.",
    )

    replay.roles(
        chief_of_staff=[route("billing")],
        billing=[tool_use("file_proposal", {**handed_on, "transfer_to": "hr"})],
        hr=[tool_use("file_proposal", answer)],
        judge=[verdict(True)],
    )

    decision = handle(request("R-203"), today=TODAY, log_directory=tmp_path)

    assert decision["proposal"]["concerns"] == []
    assert decision["flags"] == ["legal or press threat", "vulnerable person"]
    assert [notice["to"] for notice in decision["notifications"]] == [
        "Customer care manager",
        "Customer care priority line",
    ]
    assert decision["outcome"] == "held"


def test_a_second_hand_over_is_held_for_a_person_and_says_why(replay, tmp_path):
    handed_on = invoice_dispute(
        summary="A question about leave, not a bill.",
        kind="needs_attention",
        fields={"invoice_id": None, "outcome": "escalate"},
    )
    handed_back = hr_answer(
        summary="A billing question after all.",
        draft="This is about a bill, so billing should answer it.",
        transfer_to="billing",
    )

    replay.roles(
        chief_of_staff=[route("billing")],
        billing=[tool_use("file_proposal", {**handed_on, "transfer_to": "hr"})],
        hr=[tool_use("file_proposal", handed_back)],
        judge=[verdict(True)],
    )

    decision = handle(request("R-203"), today=TODAY, log_directory=tmp_path)

    assert decision["outcome"] == "held"
    assert decision["gate_reason"] == (
        "hr wants to hand it over again, to billing, and a request is handed over once"
    )
    assert len(replay.requests) == 4


@pytest.mark.parametrize(
    ("channel", "customer_id", "flagged"),
    [
        ("billing_portal", None, True),
        ("email", None, True),
        ("billing_portal", "C-1001", False),
        ("field_app", None, False),
        ("hr_portal", None, False),
    ],
)
def test_a_customers_message_with_no_customer_on_record_is_flagged_on_every_customer_channel(
    channel, customer_id, flagged
):
    assert (flags.UNVERIFIED in flags.raised([], channel, customer_id)) is flagged


@pytest.mark.parametrize("stage", [None, "", "Walk", "sprint"])
def test_a_missing_or_misspelled_stage_holds_the_request_and_never_acts_alone(stage):
    conditions = gate.Conditions(
        stage=stage, automatic_today=0, daily_cap=50, flags=[], transferred=False
    )
    passed = {"format": None, "grounded": None, "sense": None}

    assert gate.decide(report(), passed, conditions) == (
        "held",
        "field report has no stage of crawl, walk or run, so a person handles every one",
    )


def test_a_consult_that_failed_does_not_count_as_asking_the_department(replay, tmp_path):
    [label] = [label for label in labels() if label["request_id"] == "F-161"]
    filed = field_report(
        draft="Meter fine. Billing could not be reached about the October bill.",
        fields={
            "customer_id": "C-1009",
            "asset_id": "A-2009",
            "visit_date": "2026-11-24",
            "visit_date_quote": "24 Nov",
            "fault_type": "no_fault",
            "follow_up": "none",
            "readings": [{"value": 31560, "unit": "kwh", "quote": "reading 31,560 kWh"}],
        },
    )
    question = {"department": "billing", "question": "Is the October invoice of C-1009 paid?"}
    field_agent = iter([tool_use("ask_department", question), tool_use("file_proposal", filed)])
    answers = {
        "field_operations": lambda: (200, next(field_agent)),
        "billing": lambda: (400, {"error": "down"}),
        "judge": lambda: (200, verdict(True)),
        "grader": lambda: (200, grade(True)),
    }
    replay.respond(lambda body: answers[role(body)]())

    run = evaluation.run(
        "field_report", log_directory=tmp_path, today=date(2026, 11, 24), labels=[label]
    )

    assert [result.outcome for result in run.results] == ["did not ask billing"]


def test_the_environment_file_takes_quotes_and_export_and_never_overrides_the_shell(
    tmp_path, monkeypatch
):
    names = ["QUOTED", "SINGLE", "EXPORTED", "PLAIN", "COMMENTED", "FROM_SHELL"]

    for name in names:
        monkeypatch.setenv(f"UA_TEST_{name}", "")
        monkeypatch.delenv(f"UA_TEST_{name}")

    monkeypatch.setenv("UA_TEST_FROM_SHELL", "shell")
    file = tmp_path / ".env"
    file.write_text(
        'UA_TEST_QUOTED="sk-quoted"\n'
        "UA_TEST_SINGLE='one two'\n"
        "export UA_TEST_EXPORTED=yes\n"
        "UA_TEST_PLAIN = plain \n"
        "# UA_TEST_COMMENTED=1\n"
        "UA_TEST_FROM_SHELL=file\n"
    )

    cli.load_environment(file)

    assert [os.environ.get(f"UA_TEST_{name}") for name in names] == [
        "sk-quoted",
        "one two",
        "yes",
        "plain",
        None,
        "shell",
    ]


def test_every_customer_a_report_could_mean_is_on_record_and_the_agent_is_told_to_search(replay):
    unnamed = {"customer_id": None, "possible_customer_ids": ["C-1002", "C-9999"], "readings": []}
    filed = {**field_report(fields=unnamed), "kind": "needs_attention"}
    listed = new(filed, "F-1", "field_operations", "field_report")
    schema = json_schema("field_report")["properties"]["fields"]

    replay.sequence([tool_use("file_proposal", field_report())])
    department.run(
        Handoff("Kerkstraat.", "a field report", "nothing", None), working("field_report")
    )
    [playbook] = replay.requests[0]["system"]

    assert verifier.grounded(listed, "A-2002, all fine, 19-11-2026.", TODAY) == (
        "The report does not identify the customer. Possible customer C-9999 is not in the records."
    )
    assert list(schema["properties"])[:2] == ["customer_id", "possible_customer_ids"]
    assert schema["properties"]["possible_customer_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert "Always search with find_customer" in playbook["text"]
    assert "put in possible_customer_ids the ID of every customer" in playbook["text"]
