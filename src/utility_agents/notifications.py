"""Who must hear about a request now, not when they next open the queue: the team `flags` names
for each flag, and billing for a field report that affects a bill.

Two or three short sentences each, at most one per team per request, also when the request is
worked again. They are written to `notifications.jsonl` under the log directory, which stands
in for the chat message or queue a deployment would send them to.
"""

from pathlib import Path

from utility_agents import flags, json_lines
from utility_agents.proposal import FieldReport, Proposal

FILE_NAME = "notifications.jsonl"
BILLING = "Billing"
BILLING_FOLLOW_UPS = {
    "tampering": "Check for energy used without being metered (tampering)",
    "meter_accuracy": "Check the bills: the meter measured wrongly",
    "meter_replaced": "Close the old meter with its final reading",
}


def build(request_id: str, raised: list[flags.Flag], proposal: Proposal | None) -> list[dict]:
    """The notifications a request needs: `to` and `text`, from its flags and its proposal, one
    per team in the order the teams first come up. A team with several reasons, such as billing
    for money promised on site and a billing follow-up, gets them all in its one notification.
    Money tells billing only for a field report, where it means money promised on site; a
    customer's money question is already billing's."""
    reasons = [
        (team, flags.notice(flag.flag, request_id))
        for flag in raised
        if (team := _team(flag.flag, proposal)) is not None
    ]
    reasons += _billing(request_id, proposal)
    texts: dict[str, list[str]] = {}

    for team, text in reasons:
        if text not in texts.setdefault(team, []):
            texts[team].append(text)

    return [{"to": team, "text": " ".join(told)} for team, told in texts.items()]


def deliver(directory: str | Path, request_id: str, notifications: list[dict]) -> list[dict]:
    """Writes the notifications a team has not had for this request yet; returns them all."""
    path = Path(directory) / FILE_NAME
    sent = {entry["to"] for entry in json_lines.read(path) if entry["request_id"] == request_id}
    new = [notification for notification in notifications if notification["to"] not in sent]

    json_lines.append(path, [{**notification, "request_id": request_id} for notification in new])

    return notifications


def _team(flag: str, proposal: Proposal | None) -> str | None:
    if flag == "money" and proposal is not None and proposal.playbook == "field_report":
        return BILLING

    return flags.team(flag)


def _billing(request_id: str, proposal: Proposal | None) -> list[tuple[str, str]]:
    if proposal is None or not isinstance(proposal.fields, FieldReport):
        return []

    fields = proposal.fields

    if fields.billing_follow_up == "none":
        return []

    text = (
        f"Field report {request_id}: {BILLING_FOLLOW_UPS[fields.billing_follow_up]}. "
        f"Customer {fields.customer_id or ''}, meter {fields.asset_id or ''}."
    )

    return [(BILLING, text)]
