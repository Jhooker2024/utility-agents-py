import copy

from utility_agents import presenter

DECISION = {
    "request_id": "R-203",
    "playbook": "invoice_dispute",
    "outcome": "held",
    "gate_reason": "invoice dispute is at crawl, so a person handles every one",
    "checks": {
        "format": "pass",
        "grounded": "fail: €85 is not in the message or the records.",
        "sense": "pass",
    },
    "usage": {"cost_usd": 0.0123},
    "proposal": {
        "kind": "needs_attention",
        "fields": {"invoice_id": "INV-3005", "outcome": "escalate"},
        "draft": "A colleague will check the reading.",
        "unconfirmed": "Whether the October figure came from a real reading.",
        "commitments": [],
    },
}
ENTRIES = [
    {"step": "chief_of_staff", "result": "invoice_dispute", "milliseconds": 1500},
    {
        "step": "ask_department",
        "input": {"department": "field_operations", "question": "Was the meter read?"},
        "result": "ok",
        "answer": "No reading is on record.",
        "milliseconds": 9000,
    },
    {"step": "department:invoice_dispute", "result": "proposal", "milliseconds": 20_000},
]


def test_a_decision_reads_as_the_outcome_the_draft_and_why_then_the_checks_steps_and_cost():
    assert presenter.describe(DECISION, ENTRIES) == (
        "WAITING FOR A PERSON: nothing goes out until someone handles it\n"
        "\n"
        "Reply to the customer\n"
        "  A colleague will check the reading.\n"
        "\n"
        "  Invoice      October 2026 bill, 287 kWh, €91.84, open (INV-3005)\n"
        "  Outcome      Escalate\n"
        "\n"
        "Why: Invoice dispute is at crawl, so a person handles every one.\n"
        "\n"
        "Could not confirm\n"
        "  Whether the October figure came from a real reading.\n"
        "\n"
        "Checks\n"
        "  ✓ Fields valid\n"
        "  ✗ Every fact found in the message or the records\n"
        "    €85 is not in the message or the records.\n"
        "  ✓ An independent reviewer agrees it fits the message\n"
        "\n"
        "What the agents did\n"
        "  1. Front door: sent to billing (invoice dispute)\n"
        '  2. Asked field operations: "Was the meter read?"\n'
        "     Answer: No reading is on record.\n"
        "\n"
        "Cost: $0.0123, 21.5 seconds (request R-203)"
    )


def test_flags_read_as_their_labels_and_each_commitment_shows_its_words_type_and_source():
    decision = copy.deepcopy(DECISION)
    decision["flags"] = ["money asked for or promised", "legal or press threat"]
    decision["proposal"]["commitments"] = [
        {"type": "deadline", "words": "30 November", "source": "INV-3005"}
    ]

    output = presenter.describe(decision, ENTRIES)

    assert "Flags: money asked for or promised; legal or press threat" in output
    assert "Commits to   30 November (deadline, from INV-3005)" in output


def test_a_request_sent_to_a_person_shows_its_reason_once_and_no_checks():
    decision = {
        "request_id": "S-1",
        "outcome": "held",
        "proposal": None,
        "playbook": None,
        "held_reason": "The chief of staff was unsure: two topics.",
        "gate_reason": "there is no proposal to act on",
        "checks": {"format": "fail: The chief of staff was unsure: two topics."},
        "usage": {"cost_usd": 0.0001},
    }

    text = presenter.describe(decision, [])

    assert "Nothing was drafted, so a person takes this from the start." in text
    assert "Why: The chief of staff was unsure: two topics.\n" in text
    assert "Checks\n  None: there was no proposal to check.\n" in text
    assert "✗" not in text


def test_money_on_the_screen_always_shows_two_decimals():
    decision = with_proposal(fields={"invoice_id": "INV-3002"})

    assert "€396.80, open (INV-3002)" in presenter.summary(decision)


def test_long_text_wraps_at_the_screen_width_under_its_label_and_an_unknown_customer_says_so():
    long = "The technician could not reach the meter. " * 4

    decision = with_proposal(
        playbook="field_report",
        gate_reason="the agent flagged it for a person",
        fields={"customer_id": None, "asset_id": None},
        draft=long,
    )

    text = presenter.describe(decision, [])

    assert "  Customer     Not identified\n  Equipment    Not identified" in text
    assert "  Note         The technician could not reach the meter." in text
    assert all(len(line) <= 78 for line in text.split("\n"))


def test_field_report_that_affects_a_bill_tells_billing_what_to_check_and_says_nothing_otherwise():
    def report(billing):
        return with_proposal(
            playbook="field_report",
            fields={
                "customer_id": "C-1004",
                "asset_id": "A-2004",
                "follow_up": "replace_asset",
                "billing_follow_up": billing,
            },
        )

    assert "  Billing      Check the bills: the meter measured wrongly" in presenter.summary(
        report("meter_accuracy")
    )

    assert "Billing" not in presenter.summary(report("none"))


def test_a_decision_with_no_model_call_counted_reads_its_cost_as_zero_instead_of_crashing():
    text = presenter.describe({**DECISION, "usage": {"cost_usd": 0}}, ENTRIES)

    assert "Cost: $0.0000, 21.5 seconds" in text


def with_proposal(playbook=None, gate_reason=None, **proposal_changes):
    decision = copy.deepcopy(DECISION)
    decision["proposal"].update(proposal_changes)

    if playbook:
        decision["playbook"] = playbook

    if gate_reason:
        decision["gate_reason"] = gate_reason

    return decision
