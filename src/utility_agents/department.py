"""One department agent working one request with its playbook.

`run` asks the model, runs the tool it calls, sends the result back and repeats until the model
files a proposal. Parallel tool use is off, so each reply holds at most one tool call and every
call gets its result. A reply that ends without a proposal gets one nudge; an invalid proposal,
or one the fact check fails, goes back once as a tool error, so the agent can fix it. After
that, or after `MAX_TURNS` requests, the request is held for a person.

`consult` runs another department on one question with its read tools only, and returns its
text answer as the result of `ask_department`. A request may consult `MAX_CONSULTS` times.

The playbooks are read from `playbooks` when the module loads. Each file's `## Changes` section
is the playbook's dated history for staff and never reaches the prompt.
"""

from dataclasses import dataclass, replace

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from utility_agents import model, prompts, proposal, tools, trace
from utility_agents.config import PACKAGE
from utility_agents.text import words

MAX_TURNS = 8
MAX_CONSULTS = 1
NUDGE = "You have not filed a proposal. Call file_proposal now."
REQUEST_PLAYBOOKS = {entry.department: playbook for playbook, entry in proposal.PLAYBOOKS.items()}
PLAYBOOKS = {
    playbook: (PACKAGE / "playbooks" / f"{playbook}.md").read_text().split("\n## Changes")[0].strip()
    for playbook in proposal.PLAYBOOKS
}
RULES = prompts.DEPARTMENT_RULES + "\n\n" + prompts.CONCERN_RULES


@dataclass(frozen=True)
class Handoff:
    """What a department works from: the message, the intent, what was tried so far and the
    customer."""

    message: str
    intent: str
    tried: str
    customer_id: str | None


@dataclass(frozen=True)
class Worked:
    """What a department returned and the steps it took: its proposal, or the reason the
    request is held for a person, or, when it was only consulted, its answer."""

    steps: list[dict]
    proposal: proposal.Proposal | None = None
    held_reason: str | None = None
    answer: str | None = None


def request_playbook(department: str) -> str:
    return REQUEST_PLAYBOOKS[department]


def run(handoff: Handoff, context: tools.Context) -> Worked:
    """Works a handoff under `context`, which names the request, the playbook, the day and
    the models."""
    context = replace(
        context,
        department=proposal.department(context.playbook),
        message=handoff.message,
        mode="propose",
        consults_left=MAX_CONSULTS,
    )

    return _loop(context, _propose_prompt(context), _handoff_text(handoff, context))


def consult(department: str, question: str, context: tools.Context) -> str:
    """The answer of `department` to another department's question."""
    context = replace(context, department=department, mode="consult")
    worked = _loop(context, _consult_prompt(context), evidence(question))

    if worked.answer is None:
        raise tools.ToolError(f"The consulted department did not answer: {worked.held_reason}")

    return worked.answer


def evidence(text: str) -> str:
    """Text from outside, in message tags, with `<` and `>` escaped so it cannot close them."""
    escaped = text.replace("<", "&lt;").replace(">", "&gt;")

    return f"<message>\n{escaped}\n</message>"


def _loop(context: tools.Context, system: str, text: str) -> Worked:
    definitions = tools.definitions(context)
    messages: list[BaseMessage] = [HumanMessage(text)]
    steps: list[dict] = []
    nudged = corrected = False

    for _turn in range(MAX_TURNS):
        try:
            reply = model.create_message(
                context.models[context.department], system, messages, definitions
            )
        except model.ModelError as error:
            return Worked(steps, held_reason=str(error))

        stop_reason = reply.response_metadata.get("stop_reason")

        if stop_reason == "tool_use" and reply.tool_calls:
            call = reply.tool_calls[0]
            result, failure, step = _called(call, context)
            steps.append(step)

            if isinstance(result, proposal.Proposal):
                return Worked(steps, proposal=result)

            if call["name"] == "file_proposal":
                if corrected:
                    return Worked(steps, held_reason=failure)

                corrected = True

            if call["name"] == "ask_department":
                context = replace(context, consults_left=max(context.consults_left - 1, 0))

            messages += [reply, _tool_message(call, result, failure)]
        elif stop_reason == "end_turn" and context.mode == "consult":
            return Worked(steps, answer=model.text(reply))
        elif stop_reason == "end_turn" and not nudged:
            nudged = True
            messages += [reply, HumanMessage(NUDGE)]
        elif stop_reason == "end_turn":
            return Worked(steps, held_reason="The agent ended twice without filing a proposal.")
        else:
            return Worked(steps, held_reason=f"The model stopped with {stop_reason}.")

    return Worked(steps, held_reason=f"No proposal after {MAX_TURNS} model requests.")


# Runs one tool call: its result or the reason it failed, and the step for the trace. The
# filed proposal is stored once, in the decision; the trace records only that it was filed.
def _called(call: dict, context: tools.Context) -> tuple[object, str | None, dict]:
    def attempt() -> tuple[object, str | None]:
        try:
            return tools.call(call["name"], call["args"], context), None
        except tools.ToolError as error:
            return None, str(error)

    (result, failure), step = trace.timed(call["name"], attempt)
    step["input"] = None if call["name"] == "file_proposal" else call["args"]
    step["result"] = "ok" if failure is None else failure

    if call["name"] == "ask_department" and failure is None:
        step["answer"] = result

    return result, failure, step


def _tool_message(call: dict, result: object, failure: str | None) -> ToolMessage:
    if failure is None:
        return ToolMessage(content=str(result), tool_call_id=call["id"])

    return ToolMessage(content=failure, tool_call_id=call["id"], status="error")


def _propose_prompt(context: tools.Context) -> str:
    return f"{_identity(context)}\n\n{RULES}\n\n{PLAYBOOKS[context.playbook]}"


def _consult_prompt(context: tools.Context) -> str:
    return _identity(context) + "\n\n" + prompts.CONSULT_RULES


def _identity(context: tools.Context) -> str:
    return (
        f"You are the {words(context.department)} agent of a regional electricity utility. "
        f"Today is {context.today}."
    )


def _handoff_text(handoff: Handoff, context: tools.Context) -> str:
    return (
        f"Request {context.request_id}\n"
        f"Customer: {handoff.customer_id or 'not given'}\n"
        f"Intent: {handoff.intent}\n"
        f"Already tried: {handoff.tried}\n"
        "\n"
        f"{evidence(handoff.message)}\n"
    )

