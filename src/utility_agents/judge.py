"""The model half of grading; `evaluation` describes the two steps. It decides whether staff would
accept a proposal as the decision a label expects. The verdict has the reason first, so the
model reasons before it commits to a verdict.
"""

import json

from utility_agents import model, prompts, verifier
from utility_agents.text import words

HAPPENED = {
    "automatic": "it acted alone",
    "one_click": "it waits for one click from a person",
}


class Grade(model.Answer):
    reason: str
    agrees: bool


def verdict(label: dict, decision: dict, message: str, judge: str) -> verifier.Check:
    """None when the judge agrees, or the reason a decision fails against its label."""
    try:
        grade = model.structured(judge, prompts.EVAL_JUDGE, prompt(label, decision, message), Grade)
    except model.ModelError as error:
        return f"the judge request failed: {error}"
    except model.Unreadable as unreadable:
        return f"the judge gave no verdict: {json.dumps(str(unreadable), ensure_ascii=False)}"

    return None if grade.agrees else f"the judge disagrees: {grade.reason}"


def prompt(label: dict, decision: dict, message: str) -> str:
    """The judge's user message. The message and the proposal go inside tags."""
    return (
        f"{prompts.evidence(message)}\n"
        "\n"
        f"Expected decision: {expected(label)}\n"
        "\n"
        f"What happened: {HAPPENED.get(decision.get('outcome'), 'it waits for a person')}\n"
        "\n"
        "<consults>\n"
        f"{_consults(decision.get('consults'))}\n"
        "</consults>\n"
        "\n"
        "<proposal>\n"
        f"{verifier.proposal_json(decision.get('proposal'))}\n"
        "</proposal>\n"
    )


def expected(label: dict) -> str:
    """The label's decision in words: its kind, each field, then its note when it has one."""
    fields = [
        f"{words(field)} {value or 'none'}" for field, value in sorted(label["fields"].items())
    ]
    notes = [f"Note: {label['note']}"] if label.get("note") is not None else []

    return "; ".join([words(label["kind"]), *fields, *notes])


def _consults(consults: list[dict] | None) -> str:
    if not consults:
        return "It asked no other department."

    return "\n".join(
        f'It asked {words(consult["department"])}: "{consult["question"]}" '
        f'The answer: "{consult["answer"]}"'
        for consult in consults
    )
