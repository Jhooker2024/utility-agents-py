"""The proposals tests file through `file_proposal`, as the model sends them. Each takes
overrides; overrides under "fields" replace only the fields they name.
"""

from datetime import date

from utility_agents.config import settings
from utility_agents.proposal import Proposal
from utility_agents.work import Context

TODAY = date(2026, 11, 24)


def working(playbook: str, request_id: str = "F-002") -> Context:
    """What a department works one request under, on 24 November 2026."""
    return Context(today=TODAY, models=settings["models"], request_id=request_id, playbook=playbook)


def field_report(**overrides: object) -> dict:
    """A field report for customer C-1002 and meter A-2002."""
    return overridden(
        {
            "summary": "Loose neutral tightened.",
            "draft": "Loose neutral at the meter connection tightened.",
            "commitments": [],
            "kind": "record_update",
            "fields": {
                "customer_id": "C-1002",
                "asset_id": "A-2002",
                "visit_date": "2026-11-19",
                "visit_date_quote": "19-11-2026",
                "fault_type": "connection_fault",
                "follow_up": "revisit",
                "billing_follow_up": "none",
                "readings": [{"value": 9876, "unit": "kwh", "quote": "Reading 9,876 kWh"}],
            },
        },
        overrides,
    )


def hr_answer(**overrides: object) -> dict:
    """An HR answer from policy P-01."""
    return overridden(
        {
            "summary": "Answered from the policy.",
            "draft": "The policy answers your question.",
            "commitments": [],
            "kind": "reply",
            "fields": {"policy_id": "P-01"},
        },
        overrides,
    )


def invoice_dispute(**overrides: object) -> dict:
    """A reply to a dispute about invoice INV-3002, named by its number, which a colleague
    corrects."""
    return overridden(
        {
            "summary": "Estimated reading; invoice needs correcting.",
            "draft": "A colleague will correct invoice INV-3002 once the meter is read.",
            "commitments": [],
            "kind": "reply",
            "fields": {"invoice_id": "INV-3002", "invoice_quote": "INV-3002", "outcome": "correct"},
        },
        overrides,
    )


def overridden(proposal: dict, overrides: dict) -> dict:
    """A filed proposal with `overrides`; those under "fields" replace only the fields they
    name."""
    fields = {**proposal["fields"], **overrides.get("fields", {})}

    return {**proposal, **overrides, "fields": fields}


def with_fields(proposal: Proposal, **changes: object) -> Proposal:
    """A proposal with some of its playbook fields changed."""
    return proposal.model_copy(update={"fields": proposal.fields.model_copy(update=changes)})
