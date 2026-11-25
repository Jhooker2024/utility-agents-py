"""Decisions as plain text for a person reading a terminal. `summary` is what they need first:
the outcome, the drafted message or CRM update, and why. `details` is the rest: what the agent
could not confirm, the three checks, its steps, the cost and time. `steps` is the raw trace,
for a technical reader.
"""

import os
import sys
from collections.abc import Callable, Iterable
from datetime import date

from utility_agents import json_lines, proposal, records, usage
from utility_agents.notifications import BILLING_FOLLOW_UPS
from utility_agents.text import day, decimals, grouped, month, rounded, words

OUTCOMES = {
    "automatic": "DONE WITHOUT A PERSON",
    "one_click": "READY FOR ONE CLICK: a person approves it before it goes out",
    "held": "WAITING FOR A PERSON: nothing goes out until someone handles it",
}
CHECKS = (
    ("format", "Fields valid"),
    ("grounded", "Every fact found in the message or the records"),
    ("sense", "An independent reviewer agrees it fits the message"),
)
WIDTH = 78
IDENTITY_FIELDS = tuple(records.id_fields(("customer_id", "asset_id", "invoice_id")))
HEADINGS = {
    "invoice_dispute": "Reply to the customer",
    "policy_question": "Answer to the employee",
}
COLLECTIONS = {entry.collection: entry.name for entry in records.ID_FIELDS.values()} | {
    "usage": "usage record"
}
TOP_STEPS = ("chief_of_staff", "verifier", "gate")
LABELS = {
    "customer_id": "Customer",
    "asset_id": "Equipment",
    "invoice_id": "Invoice",
    "invoice_quote": "Their words",
    "policy_id": "Policy",
    "visit_date": "Visit",
    "fault_type": "Fault",
    "follow_up": "Follow-up",
    "follow_up_date": "Follow-up by",
    "billing_follow_up": "Billing",
}
FIELD_ORDER = (
    "customer_id",
    "asset_id",
    "invoice_id",
    "invoice_quote",
    "policy_id",
    "outcome",
    "visit_date",
    "fault_type",
    "follow_up",
    "follow_up_date",
    "billing_follow_up",
    "readings",
)
UNITS = {"kwh": "kWh", "volt": "V"}
COLORS = {"green": "32", "blue": "34", "red": "31", "yellow": "33", "bright": "1"}
ESCAPE = "\x1b["
RESET = ESCAPE + "0m"
REVERSE = ESCAPE + "7m"


def describe(decision: dict, entries: list[dict]) -> str:
    """A decision in full: the summary, then the details."""
    return summary(decision) + "\n\n" + details(decision, entries)


def summary(decision: dict) -> str:
    """What a person needs first: the outcome, the drafted message or CRM update the agent
    proposes, and why it went that way."""
    why = _sentence(decision.get("held_reason") or decision["gate_reason"])

    return "\n".join(
        [
            *_painted([OUTCOMES[decision["outcome"]], ""], "green"),
            *_painted(_proposal_lines(decision.get("playbook"), decision.get("proposal")), "green"),
            *_painted(_hanging("Why: ", why), "blue"),
            *_painted(_flag_lines(decision.get("flags")), "red"),
            *_painted(_notified_lines(decision.get("notifications")), "red"),
        ]
    )


def details(decision: dict, entries: list[dict]) -> str:
    """The rest: what the agent could not confirm, the checks, its steps and the cost."""
    described = [lines for lines in map(_step_lines, entries) if lines]
    steps = [line for number, lines in enumerate(described, 1) for line in _numbered(lines, number)]
    filed, request_id = decision.get("proposal"), decision["request_id"]
    cost = f"Cost: {_dollars(decision.get('usage'))}, {_seconds(entries)} (request {request_id})"

    return "\n".join(
        [
            *_painted(_notification_lines(decision.get("notifications")), "red"),
            *_painted(_unconfirmed(filed), "blue"),
            *_painted(["Checks", *_check_lines(filed, decision.get("checks"))], "blue"),
            "",
            *_painted(["What the agents did", *steps], "blue"),
            "",
            cost,
        ]
    )


def paint(text: str, color: str) -> str:
    """Text in an ANSI colour when the output is a terminal and `NO_COLOR` is not set; plain
    otherwise, so piped output, files and tests stay plain text."""
    if text == "" or not terminal() or os.environ.get("NO_COLOR"):
        return text

    return f"{ESCAPE}{COLORS[color]}m{text}{RESET}"


def plain(text: str) -> str:
    """Text without the colour codes `paint` adds: each starts with ESC [ and ends with m."""
    first, *coloured = text.split(ESCAPE)

    return first + "".join(piece.split("m", 1)[-1] for piece in coloured)


def terminal() -> bool:
    """Whether a person is at an interactive terminal, not a pipe, a file or a test."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def clear() -> None:
    """Starts a fresh screen with the cursor at the top; does nothing outside a terminal."""
    if terminal():
        sys.stdout.write(f"{ESCAPE}2J{ESCAPE}H")


def steps(entries: list[dict]) -> str:
    """A request's raw trace, one indented line per step with its input, result and time."""
    return "\n".join("  " + _trace_line(entry) for entry in entries)


def wrap(text: str, indent: int) -> str:
    """Text wrapped to the screen width, every line indented by `indent` spaces."""
    return "\n".join(" " * indent + line for line in _lines(text, WIDTH - indent))


def _step_lines(entry: dict) -> list[str]:
    step, result, arguments = entry["step"], entry.get("result"), entry.get("input") or {}

    if step == "chief_of_staff" and result.startswith("person: "):
        return ["Front door: sent to a person"]

    if step == "chief_of_staff":
        department = _department_name(proposal.department(result))

        return [f"Front door: sent to {department} ({words(result)})"]

    if step == "find_customer":
        return [f'Searched the records for "{arguments["query"]}"' + _failed(entry)]

    if step == "get_record":
        kind = COLLECTIONS.get(arguments["collection"], "")

        return [f"Read {kind} {arguments['id']}" + _failed(entry)]

    if step == "list_records":
        owner = arguments.get("customer_id")
        of_owner = "" if owner is None else f" of {owner}"

        return [f"Listed the {arguments['collection']}{of_owner}" + _failed(entry)]

    if step == "ask_department":
        asked = _department_name(arguments["department"])
        question = f'Asked {asked}: "{arguments["question"]}"' + _failed(entry)
        answer = entry.get("answer")

        return [question] if answer is None else [question, "Answer: " + answer.replace("\n", " ")]

    if step == "file_proposal" and result == "ok":
        return ["Filed its proposal"]

    if step == "file_proposal":
        return [f"Filed a proposal the schema rejected, and was told why: {result}"]

    if step == "transfer":
        return [f"Handed over to {_department_name(result)}"]

    return []


def _department_name(department: str) -> str:
    return "HR" if department == "hr" else words(department)


def _numbered(lines: list[str], number: int) -> list[str]:
    first, *rest = lines
    following = [line for text in rest for line in _hanging("     ", text)]

    return [*_hanging(f"  {number}. ", first), *following]


def _failed(entry: dict) -> str:
    return "" if entry["result"] == "ok" else f" (failed: {entry['result']})"


def _check_lines(filed: dict | None, checks: dict | None) -> list[str]:
    if filed is None:
        return ["  None: there was no proposal to check."]

    lines = []

    for check, label in CHECKS:
        if checks[check] == "pass":
            lines.append(f"  ✓ {label}")
        else:
            lines += [f"  ✗ {label}", wrap(checks[check].removeprefix("fail: "), 4)]

    return lines


def _proposal_lines(playbook: str | None, filed: dict | None) -> list[str]:
    if filed is None:
        return ["Nothing was drafted, so a person takes this from the start.", ""]

    if playbook == "field_report":
        return [
            "CRM update",
            *_field_lines(filed),
            *_field_line("Note", filed["draft"]),
            *_commitments(filed["commitments"]),
            "",
        ]

    return [
        HEADINGS[playbook],
        wrap(filed["draft"], 2),
        "",
        *_field_lines(filed),
        *_commitments(filed["commitments"]),
        "",
    ]


def _field_lines(filed: dict) -> list[str]:
    ranked = sorted(sorted(filed["fields"].items()), key=lambda pair: _field_rank(pair[0]))

    return [
        line
        for field, value in ranked
        if (value not in (None, []) or field in IDENTITY_FIELDS)
        and (field, value) != ("billing_follow_up", "none")
        for line in _field_line(_label(field), _field_text(field, value))
    ]


def _field_line(label: str, text: str) -> list[str]:
    return _hanging(f"  {label:<12} ", text)


def _field_rank(field: str) -> int:
    return FIELD_ORDER.index(field) if field in FIELD_ORDER else len(FIELD_ORDER)


def _label(field: str) -> str:
    return LABELS.get(field) or words(field).capitalize()


def _field_text(field: str, value: object) -> str:
    if value is None:
        return "Not identified"

    if field == "customer_id":
        return _record_text(
            "customers", value, lambda found: f"{found['name']}, {found['address']}"
        )

    if field == "asset_id":
        return _record_text(
            "assets",
            value,
            lambda found: f"{words(found['type']).capitalize()}, {found['location']}",
        )

    if field == "invoice_id":
        return _record_text("invoices", value, _invoice_text, department="billing")

    if field == "invoice_quote":
        return f'"{value}"'

    if field == "policy_id":
        return _record_text("policies", value, lambda found: found["title"], department="hr")

    if field == "billing_follow_up":
        return BILLING_FOLLOW_UPS[value]

    if field == "readings":
        return ", ".join(_reading(reading) for reading in value)

    if field in ("visit_date", "follow_up_date"):
        return day(date.fromisoformat(value))

    return words(value).capitalize()


def _invoice_text(invoice: dict) -> str:
    amount = "€" + decimals(invoice["amount_eur"], 2)

    return (
        f"{month(invoice['period'])} bill, {invoice['kwh_billed']} kWh, {amount}, "
        f"{invoice['status']}"
    )


def _record_text(
    collection: str,
    record_id: object,
    text: Callable[[dict], str],
    department: str = "field_operations",
) -> str:
    found = records.lookup(department, collection, record_id)

    if found is None:
        return f"{record_id}, not in the records"

    return f"{text(found)} ({record_id})"


def _reading(reading: dict) -> str:
    return f"{grouped(str(rounded(reading['value'])), ',')} {UNITS[reading['unit']]}"


def _commitments(commitments: list[dict]) -> list[str]:
    if not commitments:
        return []

    listed = ", ".join(
        f"{commitment['words']} ({commitment['type']}, from {commitment['source']})"
        for commitment in commitments
    )

    return _field_line("Commits to", listed)


def _unconfirmed(filed: dict | None) -> list[str]:
    text = (filed or {}).get("unconfirmed")

    return ["Could not confirm", wrap(text, 2), ""] if text else []


def _dollars(counted: dict | None) -> str:
    cost = (counted or {}).get("cost_usd")

    return "price unknown" if cost is None else usage.dollars(cost)


def _painted(lines: Iterable[str], color: str) -> list[str]:
    return [paint(part, color) for line in lines for part in line.split("\n")]


def _flag_lines(flags: list[str] | None) -> list[str]:
    return _hanging("Flags: ", "; ".join(flags)) if flags else []


def _notified_lines(notifications: list[dict] | None) -> list[str]:
    if not notifications:
        return []

    return _hanging("Notified: ", ", ".join(notification["to"] for notification in notifications))


def _notification_lines(notifications: list[dict] | None) -> list[str]:
    if not notifications:
        return []

    lines = [
        line
        for notification in notifications
        for line in _hanging(f"  {notification['to']}: ", notification["text"])
    ]

    return ["Notifications", *lines, ""]


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:].rstrip(".") + "."


def _hanging(label: str, text: str) -> list[str]:
    first, *rest = _lines(text, WIDTH - len(label))

    return [label + first, *(" " * len(label) + line for line in rest)]


def _lines(text: str, width: int) -> list[str]:
    return [line for paragraph in text.split("\n") for line in _wrapped(paragraph, width)]


# Words fill a line until the next would reach the width, counted in bytes as the Elixir
# version did, so a line with "€" or "✓" breaks at the same word.
def _wrapped(paragraph: str, width: int) -> list[str]:
    lines, line = [], ""

    for word in filter(None, paragraph.split(" ")):
        if not line:
            line = word
        elif len(line.encode()) + len(word.encode()) >= width:
            lines.append(line)
            line = word
        else:
            line += " " + word

    return [*lines, line]


def _seconds(entries: list[dict]) -> str:
    milliseconds = sum(
        entry["milliseconds"]
        for entry in entries
        if entry["step"] in TOP_STEPS or entry["step"].startswith("department:")
    )

    return f"{rounded(milliseconds / 1000, 1)} seconds"


def _trace_line(entry: dict) -> str:
    result, milliseconds = entry.get("result", ""), entry["milliseconds"]

    return f"{entry['step']}{_trace_input(entry)} -> {result} ({milliseconds} ms)"


def _trace_input(entry: dict) -> str:
    if entry["step"] == "file_proposal" or "input" not in entry:
        return ""

    return " " + json_lines.compact(entry["input"])[:90]
