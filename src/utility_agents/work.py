"""The values that travel along the request path: the request, the handoff a department works
from, the context it works under and what it returns.
"""

from dataclasses import dataclass, field
from datetime import date

from utility_agents.proposal import Proposal


@dataclass(frozen=True)
class Request:
    """A request as the path takes it."""

    id: str
    channel: str
    customer_id: str | None
    message: str


@dataclass(frozen=True)
class Handoff:
    """What a department works from: the message, the intent, what was tried so far and the
    customer."""

    message: str
    intent: str
    tried: str
    customer_id: str | None


@dataclass(frozen=True)
class Context:
    """What a department works under: the day, the model of every role and the log directory,
    and for one request its ID, playbook, department, message and the customer it is from.
    `mode` is `propose` for the department that files the proposal and `consult` for one that
    only answers a question."""

    today: date
    models: dict[str, str]
    log_directory: str = ""
    request_id: str = ""
    playbook: str = ""
    department: str = ""
    message: str = ""
    customer_id: str | None = None
    mode: str = "propose"


@dataclass(frozen=True)
class Worked:
    """What a department returned and the steps it took: its proposal, or the reason the
    request is held for a person, or, when it was only consulted, its answer."""

    steps: list[dict] = field(default_factory=list)
    proposal: Proposal | None = None
    held_reason: str | None = None
    answer: str | None = None
