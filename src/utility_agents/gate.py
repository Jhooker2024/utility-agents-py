"""Decides what happens to a proposal: `held` for a person to handle, `one_click` for a person
to approve, or `automatic`. A pure function of the proposal, the checks and the conditions:
the playbook's stage, the automatic actions so far today, the daily cap, the flags from the
structured concerns (`flags`) and whether the request was handed over between departments.
Every input is a structured field or a count; nothing reads the message text.

Crawl holds everything. Walk lets `record_update` act alone (file a CRM update) and makes
`reply` one click. Run acts alone. A stage that is missing or is none of these holds. At every
stage `needs_attention`, which the agent files when it wants a person, holds.

Any failed check or flag holds, and so does a proposal that names a second transfer: a request
is handed over once. An automatic outcome becomes one click past the daily cap, when
the proposal lists commitments, when the agent could not confirm something, when the request
was handed over between departments, and always for the `NEVER_AUTOMATE` playbooks, whatever
their configured stage.
"""

from dataclasses import dataclass

from utility_agents.flags import Flag
from utility_agents.proposal import Proposal
from utility_agents.text import words

NEVER_AUTOMATE = ("invoice_dispute",)
FAILED_CHECKS = {
    "format": "the fields are invalid",
    "grounded": "the fact check failed",
    "sense": "the independent reviewer disagrees",
}


@dataclass(frozen=True)
class Conditions:
    stage: str | None
    automatic_today: int
    daily_cap: int
    flags: list[Flag]
    transferred: bool


def decide(proposal: Proposal | None, checks: dict, conditions: Conditions) -> tuple[str, str]:
    """The outcome and its reason. The reason names only what decided the outcome: what held
    it, or what made an automatic action one click, or else the stage. A dispute at crawl
    names the stage and everything else that would hold it."""
    if proposal is None:
        return "held", "there is no proposal to act on"

    outcome, stage_reason = _by_stage(proposal, conditions.stage)
    stops = _stop_reasons(proposal, checks, conditions)
    limits = _limit_reasons(proposal, conditions)

    if outcome == "held":
        return "held", "; ".join([stage_reason, *stops])

    if stops:
        return "held", "; ".join(stops)

    if outcome == "automatic" and limits:
        return "one_click", "; ".join(limits)

    return outcome, "; ".join([stage_reason, *limits])


def _by_stage(proposal: Proposal, stage: str | None) -> tuple[str, str]:
    if stage == "crawl":
        return "held", f"{words(proposal.playbook)} is at crawl, so a person handles every one"

    # A proposal the agent itself flagged for a person never acts alone, at any stage.
    if proposal.kind == "needs_attention":
        return "held", f"the agent flagged it for a person: {proposal.summary}"

    if stage == "walk" and proposal.kind == "record_update":
        return "automatic", "at walk, safe internal work acts alone"

    if stage == "walk":
        return "one_click", "at walk, a customer reply needs one click"

    if stage == "run":
        return "automatic", f"{words(proposal.playbook)} is at run"

    return "held", (
        f"{words(proposal.playbook)} has no stage of crawl, walk or run, "
        "so a person handles every one"
    )


def _stop_reasons(proposal: Proposal, checks: dict, conditions: Conditions) -> list[str]:
    failed = [f"{FAILED_CHECKS[check]}: {reason}" for check, reason in checks.items() if reason]
    reasons = []

    if failed:
        reasons.append("; ".join(failed))

    if conditions.flags:
        reasons.append("flagged: " + ", ".join(flag.label for flag in conditions.flags))

    if conditions.transferred and proposal.transfer_to is not None:
        reasons.append(
            f"{words(proposal.department)} wants to hand it over again, to "
            f"{words(proposal.transfer_to)}, and a request is handed over once"
        )

    return reasons


def _limit_reasons(proposal: Proposal, conditions: Conditions) -> list[str]:
    promised = ", ".join(commitment.words for commitment in proposal.commitments)
    limits = [
        (proposal.playbook in NEVER_AUTOMATE, f"{words(proposal.playbook)} never acts alone"),
        (bool(proposal.commitments), f"it makes a commitment: {promised}"),
        (bool(proposal.unconfirmed), "the agent could not confirm everything"),
        (conditions.transferred, "it was handed over between departments"),
        (
            conditions.automatic_today >= conditions.daily_cap,
            f"the daily cap of {conditions.daily_cap} automatic actions is reached",
        ),
    ]

    return [reason for applies, reason in limits if applies]
