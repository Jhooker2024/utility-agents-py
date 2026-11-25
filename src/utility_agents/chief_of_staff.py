"""The front door. A request from a mapped channel (`channel_routes`) goes straight to that
department and playbook, with no model call: a field report comes only through the field app
and an HR question only through the HR portal. Free text, such as email or chat, comes from
anyone, so the chief of staff's model may only route it to billing. When the model is unsure,
or the call fails, the request goes to a person's queue. The model also names the concerns the
message raises, from the same list as a department's proposal, so a message that goes to a
person still raises its flags.

It returns the playbook and the handoff the department works from: the message, the intent,
what was tried so far and the customer.
"""

from dataclasses import dataclass

from pydantic import Field

from utility_agents import flags, model, prompts, proposal
from utility_agents.config import settings
from utility_agents.work import Context, Handoff, Request

UNSURE = "unsure"
FREE_TEXT_DEPARTMENTS = ("billing",)
SYSTEM = prompts.CHIEF_OF_STAFF + "\n\n" + prompts.CONCERN_RULES


class Route(model.Answer):
    """The chief of staff's answer, reason first. The schema limits the department and the
    concerns to the listed values; the code checks them again, so an answer outside them still
    goes to a person with its reason."""

    reason: str
    department: str = Field(json_schema_extra={"enum": [*FREE_TEXT_DEPARTMENTS, UNSURE]})
    intent: str
    concerns: list[str] = Field(
        json_schema_extra={"items": {"type": "string", "enum": list(flags.CONCERNS)}}
    )


@dataclass(frozen=True)
class Routed:
    playbook: str
    handoff: Handoff


@dataclass(frozen=True)
class Person:
    """A request for a person's queue, with the concerns the model named."""

    reason: str
    concerns: list[str]


def route(request: Request, context: Context) -> Routed | Person:
    """Where a request goes. A mapped channel never goes to a person here, so only the model
    names concerns."""
    playbook = settings["channel_routes"].get(request.channel)

    if playbook is not None:
        return Routed(playbook, _handoff(request, playbook))

    try:
        answer = model.structured(
            context.models["chief_of_staff"], SYSTEM, prompts.evidence(request.message), Route
        )
    except model.ModelError as error:
        return Person(f"Routing failed: {error}", [])
    except model.Unreadable:
        return Person("Routing failed: the model gave no department.", [])

    if answer.department == UNSURE:
        concerns = [name for name in answer.concerns if name in flags.CONCERNS]

        return Person(f"The chief of staff was unsure: {answer.reason}", concerns)

    if answer.department not in FREE_TEXT_DEPARTMENTS:
        return Person("Routing failed: free text may only go to billing.", [])

    playbook = proposal.request_playbook(answer.department)

    return Routed(playbook, _handoff(request, answer.intent))


def _handoff(request: Request, intent: str) -> Handoff:
    return Handoff(
        message=request.message,
        intent=intent,
        tried="nothing yet",
        customer_id=request.customer_id,
    )
