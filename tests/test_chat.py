import io
from pathlib import Path

import pytest

from tests.support.fixtures import field_report, hr_answer, invoice_dispute, overridden
from tests.support.replay import tool_use, verdict
from utility_agents import chat, json_lines, request_path
from utility_agents.config import settings


@pytest.fixture
def proposal():
    today = request_path.utc_today()

    return field_report(
        summary="Blown fuse replaced.",
        draft="The meter display was blank because of a blown fuse. The fuse was replaced.",
        fields={
            "visit_date": today.isoformat(),
            "visit_date_quote": None,
            "follow_up": "none",
            "readings": [{"value": 9950, "unit": "kwh", "quote": "9,950 kWh"}],
        },
    )


def test_a_field_report_in_your_own_words_shows_the_crm_update_first_and_the_steps_on_request(
    replay, proposal, monkeypatch, capsys
):
    replay.sequence(
        [
            tool_use("find_customer", {"query": "Jansen Kerkstraat"}),
            tool_use("file_proposal", proposal),
            verdict(True),
        ]
    )

    report = "Bram Jansen, Kerkstraat 4. Display blank, blown fuse replaced. Reading 9,950 kWh."
    # Field report, the report, then "show the checks", "back", quit.
    output = typed(f"3\n{report}\n1\n3\n6\n", monkeypatch, capsys)

    handoff = first_message(replay.requests[0])

    assert "Write what happened on the visit" in output
    assert "Sent from the field app on " in handoff
    assert report in handoff
    assert "DONE WITHOUT A PERSON" in output
    assert "Customer     Bram Jansen, Kerkstraat 4, Deventer (C-1002)" in output
    assert "Readings     9,950 kWh" in output
    assert "1. Front door: sent to field operations (field report)" in output
    assert '2. Searched the records for "Jansen Kerkstraat"' in output
    assert "✓ Fields valid" in output
    assert "Cost: $0.0000, " in output


def test_a_report_that_does_not_say_which_meter_offers_the_customers_and_runs_again_with_it(
    replay, proposal, monkeypatch, capsys
):
    unmatched = overridden(proposal, {"fields": {"asset_id": "A-9999"}})
    open_report = for_a_person(proposal, asset_id=None)

    # The fact check sends the unknown meter back; the agent files it for a person instead.
    replay.sequence(
        [
            tool_use("file_proposal", unmatched),
            tool_use("file_proposal", open_report),
            verdict(True),
            tool_use("file_proposal", proposal),
            verdict(True),
        ]
    )

    # Field report, the report, the customer's one meter picked from the list, "back", quit.
    text = "3\nKerkstraat. Blown fuse replaced, 9,950 kWh.\n1\n3\n6\n"
    output = typed(text, monkeypatch, capsys)

    handoff = first_message(replay.requests[3])

    assert "The report does not say which meter it was." in output
    assert "Which meter or cable was it?" in output
    assert "  1  Smart meter, Kerkstraat 4, Deventer (A-2002)" in output
    assert "  2  I don't know: leave it for a person" in output
    assert "Approve the draft as it is" not in output
    assert "Reject it: it should not have gone ahead" in output
    assert "Added by the technician: smart meter A-2002" in handoff


def test_a_draft_waiting_for_a_person_is_shown_and_can_be_approved_as_a_staff_review(
    replay, monkeypatch, capsys
):
    answer = hr_answer(
        summary="Carry-over answered from the leave policy.",
        draft="Up to 5 unused days carry over and expire on 1 July.",
        kind="needs_attention",
    )

    replay.sequence([tool_use("file_proposal", answer), verdict(True)])

    # HR, the question, "approve as it is", "back", quit.
    output = typed("1\nDo my unused leave days carry over?\n2\n5\n6\n", monkeypatch, capsys)

    handoff = first_message(replay.requests[0])

    assert "An employee can ask about these policies:\n  - Annual leave\n  - Remote work" in output
    assert "Do my unused leave days carry over?" in handoff
    assert "WAITING FOR A PERSON" in output
    assert "Answer to the employee" in output
    assert "  Up to 5 unused days carry over and expire on 1 July." in output
    assert "Recorded as a staff review." in output

    stored = json_lines.read(Path(settings["log_directory"]) / "decisions.jsonl")[-1]

    assert stored["type"] == "review"
    assert stored["action"] == "sent_unedited"
    assert stored["kind"] == "needs_attention"


def test_a_field_report_held_with_no_proposal_asks_for_nothing_and_offers_no_approval(
    replay, monkeypatch, capsys
):
    replay.always(400, {"error": "bad request"})

    output = typed("3\nKerkstraat. Blown fuse replaced.\n2\n6\n", monkeypatch, capsys)

    assert "WAITING FOR A PERSON" in output
    assert "Nothing was drafted, so a person takes this from the start." in output
    assert "does not say which" not in output
    assert "Approve" not in output
    assert len(replay.requests) == 1


def test_a_customers_message_goes_straight_to_billing_with_the_customer_known_by_their_email(
    replay, monkeypatch, capsys
):
    dispute = invoice_dispute(
        summary="Customer questions the October amount.",
        draft="A colleague will check your October invoice and get back to you.",
        kind="needs_attention",
        fields={"invoice_id": None, "invoice_quote": None, "outcome": "escalate"},
    )

    replay.sequence([tool_use("file_proposal", dispute), verdict(True)])

    # Billing, Anna's email, the message, "show the checks", "back", quit.
    text = "2\nanna.devries@example.com\nMy bill is too high.\n1\n5\n6\n"
    output = typed(text, monkeypatch, capsys)

    [system] = replay.requests[0]["system"]

    assert "A customer can write about:\n  - a bill that is higher than expected" in output
    assert "From Anna de Vries (C-1001), known by their email address." in output
    assert "WAITING FOR A PERSON" in output
    assert "1. Front door: sent to billing (invoice dispute)" in output
    assert "You are the billing agent" in system["text"]


def test_i_dont_know_at_the_missing_meter_leaves_it_for_a_person_and_sends_nothing_more(
    replay, proposal, monkeypatch, capsys
):
    open_report = for_a_person(proposal, asset_id=None)

    replay.sequence([tool_use("file_proposal", open_report), verdict(True)])

    # Field report, the report, "I don't know" at the meter question, "back", quit.
    output = typed("3\nKerkstraat. Blown fuse replaced.\n2\n4\n6\n", monkeypatch, capsys)

    assert "Which meter or cable was it?" in output
    assert "WAITING FOR A PERSON" in output
    assert len(replay.requests) == 2


@pytest.mark.parametrize(
    ("possible", "answers", "added"),
    [
        (["C-1002"], "1\n", "customer Bram Jansen, Kerkstraat 4, Deventer (C-1002)"),
        (
            ["C-1007"],
            "1\n2\n",
            "customer Gerrit Mulder, Industrieweg 50, Zwolle (C-1007); service cable A-2011",
        ),
        (
            ["C-1002"],
            "2\nPieter de Boer, Kerkstraat 9\n\n",
            "customer Pieter de Boer, Kerkstraat 9",
        ),
        (["C-1002"], "3\nA-2002\n", "meter A-2002"),
        (["C-9999"], "Bram Jansen\n\n", "customer Bram Jansen"),
        (["C-1002"], "3\n\n", None),
        ([], "\n\n", None),
    ],
)
def test_a_report_that_names_no_customer_offers_the_ones_it_could_mean_and_runs_again_once(
    possible, answers, added, replay, proposal, monkeypatch, capsys
):
    street_only = for_a_person(
        proposal, customer_id=None, asset_id=None, possible_customer_ids=possible
    )
    again = [tool_use("file_proposal", proposal), verdict(True)] if added else []

    replay.sequence([tool_use("file_proposal", street_only), verdict(True), *again])

    # Field report, the report, the answers, "back" (the third or fourth choice), quit.
    back = 3 if added else 4
    text = f"3\nreplaced the fuse at kerkstraat, now 9,950 kWh\n{answers}{back}\n6\n"
    output = typed(text, monkeypatch, capsys)

    assert "The report does not say which customer or meter it was." in output
    assert len(replay.requests) == (4 if added else 2)

    if added:
        assert f"Added by the technician: {added}" in first_message(replay.requests[2])


def test_a_street_only_report_shows_who_it_could_be_and_offers_them_by_name(
    replay, proposal, monkeypatch, capsys
):
    street_only = for_a_person(
        proposal, customer_id=None, asset_id=None, possible_customer_ids=["C-1002", "C-1005"]
    )

    replay.sequence([tool_use("file_proposal", street_only), verdict(True)])

    # Field report, the report, "I don't know" for the customer, Enter for the meter, back, quit.
    output = typed("3\nfuse replaced, kerkstraat or schoolstraat\n4\n\n4\n6\n", monkeypatch, capsys)

    assert "  Customer     Not identified" in output
    assert (
        "  Could be     Bram Jansen, Kerkstraat 4, Deventer (C-1002); Esra Yilmaz,\n"
        "               Schoolstraat 21, Hattem (C-1005)"
    ) in output
    assert "Which customer was it?" in output
    assert "  1  Bram Jansen, Kerkstraat 4, Deventer (C-1002)" in output
    assert "  2  Esra Yilmaz, Schoolstraat 21, Hattem (C-1005)" in output
    assert "  3  Someone else: type a name and street" in output
    assert "  4  I don't know: leave it for a person" in output
    assert "Which meter was it? The meter number (press Enter if you don't know): " in output


def test_a_field_report_asks_for_what_is_missing_once_and_never_again_after_the_second_run(
    replay, proposal, monkeypatch, capsys
):
    unknown = for_a_person(proposal, customer_id=None, asset_id=None)

    replay.sequence(
        [
            tool_use("file_proposal", unknown),
            verdict(True),
            tool_use("file_proposal", unknown),
            verdict(True),
        ]
    )

    # Field report, the report, two answers that settle nothing, "back", quit.
    output = typed("3\nfuse replaced somewhere\nsdfvv\nno idea\n4\n6\n", monkeypatch, capsys)

    assert output.count("The report does not say which customer or meter it was.") == 1
    assert output.count("WAITING FOR A PERSON") == 2
    assert len(replay.requests) == 4


@pytest.mark.parametrize("keys", ["1\n\n6\n", "2\n\n\n6\n", "3\n\n6\n"])
def test_enter_on_an_empty_line_goes_back_to_the_menu_and_sends_nothing(
    keys, replay, monkeypatch, capsys
):
    output = typed(keys, monkeypatch, capsys)

    assert "(or press Enter to go back)" in output
    assert output.count("What do you want to do?") == 2
    assert replay.requests == []


def test_a_customer_with_no_email_is_not_on_record_and_an_unknown_menu_choice_is_explained(
    replay, monkeypatch, capsys
):
    replay.always(400, {"error": "bad request"})

    output = typed("9\nq\n2\n\nMy bill is too high.\n2\n6\n", monkeypatch, capsys)

    assert "Type a number from the list." in output
    assert "From someone not on record" in output
    assert len(replay.requests) == 1


def test_the_evals_menu_runs_all_three_playbooks_and_prints_each_report(
    replay, monkeypatch, capsys
):
    replay.always(400, {"error": "bad request"})

    output = typed("5\n4\n6\n", monkeypatch, capsys)

    for playbook in ["field_report", "invoice_dispute", "policy_question"]:
        assert f"Playbook {playbook}: " in output


def for_a_person(proposal: dict, **fields: object) -> dict:
    """The report filed for a person instead, with these fields replaced."""
    return overridden(proposal, {"kind": "needs_attention", "fields": fields})


def typed(text, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    chat.start()

    return capsys.readouterr().out


def first_message(request_body):
    [message] = request_body["messages"]

    return message["content"]
