from datetime import date
from pathlib import Path

import pytest

from utility_agents import flags, json_lines, notifications, prompts
from utility_agents.proposal import FieldReport, PolicyQuestion, Proposal

REPORT = Proposal(
    request_id="F-001",
    department="field_operations",
    playbook="field_report",
    kind="record_update",
    summary="Loose neutral tightened.",
    draft="Loose neutral at the meter connection tightened.",
    fields=FieldReport(
        customer_id="C-1004",
        asset_id="A-2004",
        visit_date=date(2026, 11, 19),
        fault_type="connection_fault",
        follow_up="revisit",
        billing_follow_up="none",
    ),
)
POLICY = Proposal(
    request_id="R-1",
    department="hr",
    playbook="policy_question",
    kind="reply",
    summary="Answered from the policy.",
    draft="The policy answers your question.",
    fields=PolicyQuestion(policy_id="P-01"),
)


@pytest.mark.parametrize(
    ("concern", "proposal", "team"),
    [
        ("safety", REPORT, "Field operations duty desk"),
        ("outage", None, "Field operations duty desk"),
        ("tampering", REPORT, "Revenue protection"),
        ("vulnerable", None, "Customer care priority line"),
        ("instructions", REPORT, "Security"),
        ("personal", POLICY, "HR, in confidence"),
        ("legal", None, "Customer care manager"),
        ("money", REPORT, "Billing"),
    ],
)
def test_each_concern_tells_the_team_that_handles_it(concern, proposal, team):
    raised = flags.raised([concern], "field_app", "C-1004")

    built = notifications.build("R-1", raised, proposal)

    assert [notification["to"] for notification in built] == [team], concern


def test_a_customers_money_question_and_an_unknown_sender_tell_no_team_billing_already_has_it():
    raised = flags.raised(["money"], "email", None)
    dispute = POLICY.model_copy(update={"playbook": "invoice_dispute"})

    assert [flag.flag for flag in raised] == ["money", "unverified"]
    assert notifications.build("R-2", raised, dispute) == []


def test_flags_and_a_billing_follow_up_notify_each_team_once_even_when_worked_again(tmp_path):
    raised = flags.raised(["safety", "safety"], "field_app", "C-1004")
    proposal = meter_accuracy(REPORT)

    built = notifications.build("F-015", raised, proposal)

    assert built == [
        {
            "to": "Field operations duty desk",
            "text": "Request F-015 reports a safety risk. Check it today; it waits for a person.",
        },
        {
            "to": "Billing",
            "text": "Field report F-015: Check the bills: the meter measured wrongly. "
            "Customer C-1004, meter A-2004.",
        },
    ]

    notifications.deliver(tmp_path, "F-015", built)
    notifications.deliver(tmp_path, "F-015", built)

    sent = json_lines.read(Path(tmp_path) / "notifications.jsonl")
    assert [entry["to"] for entry in sent] == ["Field operations duty desk", "Billing"]


def test_a_team_with_two_reasons_gets_both_in_one_notification_not_only_the_first():
    raised = flags.raised(["money"], "field_app", "C-1004")
    proposal = meter_accuracy(REPORT)

    built = notifications.build("F-026", raised, proposal)

    assert [notification["to"] for notification in built] == ["Billing"]
    text = built[0]["text"]
    assert "says money was promised to the customer" in text
    assert "Check the bills: the meter measured wrongly. Customer C-1004, meter A-2004." in text


def test_every_concern_has_a_label_and_a_notice_and_the_agents_rules_define_every_one():
    rules = prompts.CONCERN_RULES

    for concern in flags.CONCERNS:
        assert flags.label(concern) != ""
        assert "R-1" in flags.notice(concern, "R-1")
        assert f"- {concern}:" in rules, f"the concern rules do not define {concern}"

    assert "safety" in flags.CONCERNS
    assert "made_up" not in flags.CONCERNS


def meter_accuracy(report):
    fields = report.fields.model_copy(update={"billing_follow_up": "meter_accuracy"})

    return report.model_copy(update={"fields": fields})
