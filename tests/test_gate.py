import dataclasses
from datetime import date

import pytest

from utility_agents import gate
from utility_agents.config import settings
from utility_agents.flags import Flag
from utility_agents.proposal import Commitment, FieldReport, Proposal

PASSED = {"format": None, "grounded": None, "sense": None}
KINDS = ["record_update", "reply", "needs_attention"]


@pytest.fixture
def conditions():
    return gate.Conditions(
        stage="walk",
        automatic_today=0,
        daily_cap=settings["daily_cap"],
        flags=[],
        transferred=False,
    )


@pytest.fixture
def proposal():
    return Proposal(
        request_id="F-001",
        department="field_operations",
        playbook="field_report",
        kind="record_update",
        summary="Loose neutral tightened.",
        draft="Loose neutral at the meter connection tightened.",
        commitments=[],
        fields=FieldReport(
            customer_id="C-1002",
            asset_id="A-2002",
            visit_date=date(2026, 11, 19),
            fault_type="connection_fault",
            follow_up="revisit",
            billing_follow_up="none",
        ),
    )


def test_stage_by_kind(conditions, proposal):
    outcomes = [
        outcome(proposal, kind, stage, conditions)
        for stage in ["crawl", "walk", "run"]
        for kind in KINDS
    ]

    crawl = ["held", "held", "held"]
    walk = ["automatic", "one_click", "held"]
    run = ["automatic", "automatic", "held"]

    assert outcomes == crawl + walk + run


def test_a_failed_check_or_no_proposal_holds(conditions, proposal):
    at_run = dataclasses.replace(conditions, stage="run")

    assert gate.decide(proposal, {**PASSED, "sense": "x"}, at_run)[0] == "held"
    assert gate.decide(None, PASSED, at_run)[0] == "held"


def test_an_automatic_outcome_is_one_click_past_the_cap_or_with_commitments(conditions, proposal):
    at_run = dataclasses.replace(conditions, stage="run")

    assert gate.decide(proposal, PASSED, dataclasses.replace(at_run, automatic_today=49))[0] == (
        "automatic"
    )
    assert gate.decide(proposal, PASSED, dataclasses.replace(at_run, automatic_today=50))[0] == (
        "one_click"
    )

    deadline = Commitment(type="deadline", words="30 November", source="INV-3001")

    assert gate.decide(proposal.model_copy(update={"commitments": [deadline]}), PASSED, at_run) == (
        "one_click",
        "it makes a commitment: 30 November",
    )

    assert gate.decide(
        proposal.model_copy(update={"unconfirmed": "Which meter."}), PASSED, at_run
    ) == ("one_click", "the agent could not confirm everything")

    assert gate.decide(proposal, PASSED, dataclasses.replace(at_run, transferred=True)) == (
        "one_click",
        "it was handed over between departments",
    )


def test_a_flag_or_a_failed_check_holds_and_says_why_in_words(conditions, proposal):
    flags = [Flag("safety", "safety risk"), Flag("legal", "legal or press threat")]

    assert gate.decide(proposal, PASSED, dataclasses.replace(conditions, flags=flags)) == (
        "held",
        "flagged: safety risk, legal or press threat",
    )

    failed = {**PASSED, "grounded": "Reading 9867 is not in the report."}

    assert gate.decide(proposal, failed, conditions) == (
        "held",
        "the fact check failed: Reading 9867 is not in the report.",
    )


def test_invoice_disputes_never_act_alone_whatever_the_stage(conditions, proposal):
    outcomes = [
        outcome(
            proposal.model_copy(update={"playbook": "invoice_dispute"}), kind, stage, conditions
        )
        for stage in ["walk", "run"]
        for kind in KINDS
    ]

    assert "automatic" not in outcomes


def test_every_outcome_says_why(conditions, proposal):
    reply = proposal.model_copy(update={"kind": "reply"})

    assert gate.decide(reply, PASSED, conditions) == (
        "one_click",
        "at walk, a customer reply needs one click",
    )

    flagged = proposal.model_copy(
        update={"kind": "needs_attention", "summary": "The meter seal is broken."}
    )

    assert gate.decide(flagged, PASSED, conditions) == (
        "held",
        "the agent flagged it for a person: The meter seal is broken.",
    )

    assert gate.decide(
        proposal.model_copy(update={"playbook": "invoice_dispute"}), PASSED, conditions
    ) == ("one_click", "invoice dispute never acts alone")

    dispute = reply.model_copy(update={"playbook": "invoice_dispute"})
    flags = [Flag("money", "money asked for or promised")]

    assert gate.decide(
        dispute, PASSED, dataclasses.replace(conditions, stage="crawl", flags=flags)
    ) == (
        "held",
        "invoice dispute is at crawl, so a person handles every one; "
        "flagged: money asked for or promised",
    )


def test_the_settings_that_bound_what_acts_alone():
    assert settings["daily_cap"] == 50

    assert settings["stages"] == {
        "invoice_dispute": "crawl",
        "field_report": "walk",
        "policy_question": "run",
    }


def outcome(proposal, kind, stage, conditions):
    decided, _reason = gate.decide(
        proposal.model_copy(update={"kind": kind}),
        PASSED,
        dataclasses.replace(conditions, stage=stage),
    )

    return decided
