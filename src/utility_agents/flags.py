"""The flags on a request. Each is a concern from the structured answer of the model that decided
the request: the chief of staff when it sent a message to a person's queue, the department
agent otherwise. The schema limits concerns to the ones in `CONCERNS`, so no text is parsed
here. One flag comes from code: a customer's message from a sender not on record, on any
channel that is not one of the `staff_channels`.

Any flag holds the request for a person; `notifications` tells the team that handles it.
`CONCERNS` is the one table of concerns: in the order the schemas list them, each with its
label, the team that hears about it and what that team is told ({id} is the request ID). Money
has no team here: `notifications` decides who hears about it.
"""

from typing import Literal, NamedTuple

from utility_agents.config import settings


class Concern(NamedTuple):
    label: str
    team: str | None
    notice: str


class Flag(NamedTuple):
    flag: str
    label: str


CONCERNS = {
    "safety": Concern(
        "safety risk",
        "Field operations duty desk",
        "Request {id} reports a safety risk. Check it today; it waits for a person.",
    ),
    "outage": Concern(
        "power outage",
        "Field operations duty desk",
        "Request {id} reports a power outage. Check the network; it waits for a person.",
    ),
    "vulnerable": Concern(
        "vulnerable person",
        "Customer care priority line",
        "Request {id} mentions a vulnerable person. Call back today; it waits for a person.",
    ),
    "tampering": Concern(
        "possible tampering",
        "Revenue protection",
        "Request {id} shows possible tampering. Check the meter and the account.",
    ),
    "instructions": Concern(
        "instructions to the AI",
        "Security",
        "Request {id} contains instructions to the AI. They were not followed; check who sent it.",
    ),
    "personal": Concern(
        "personal situation for HR",
        "HR, in confidence",
        "An employee's message ({id}) needs HR in person. Contact them in confidence; "
        "no answer went out.",
    ),
    "legal": Concern(
        "legal or press threat",
        "Customer care manager",
        "Request {id} threatens legal or press action. A manager should reply.",
    ),
    "money": Concern(
        "money asked for or promised",
        None,
        "Field report {id} says money was promised to the customer. Decide before anyone pays.",
    ),
}
UNVERIFIED = Flag("unverified", "sender not on record: share no account details")

ConcernName = Literal[*CONCERNS]


def label(concern: str) -> str:
    return CONCERNS[concern].label


def team(flag: str) -> str | None:
    """The team that hears about a flag, or None."""
    if flag == UNVERIFIED.flag:
        return None

    return CONCERNS[flag].team


def notice(concern: str, request_id: str) -> str:
    """What the team hears about a concern on request `request_id`."""
    return CONCERNS[concern].notice.replace("{id}", request_id)


def raised(concerns: list[str], channel: str, customer_id: str | None) -> list[Flag]:
    """A flag for each concern, in the order given, plus the unverified-sender flag for a
    customer's message with no customer ID: any channel but the ones staff write on."""
    named = [Flag(concern, label(concern)) for concern in dict.fromkeys(concerns)]

    if customer_id is None and channel not in settings["staff_channels"]:
        return [*named, UNVERIFIED]

    return named
