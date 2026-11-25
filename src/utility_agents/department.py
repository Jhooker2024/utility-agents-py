"""One department agent working one request with its playbook.

`run` asks the model, runs the tool it calls, sends the result back and repeats until the model
files a proposal. Parallel tool use is off, so each reply holds at most one tool call and every
call gets its result. A reply that ends without a proposal gets one nudge; an invalid proposal,
or one the fact check fails, goes back once as a tool error, so the agent can fix it. After
that, or after `MAX_TURNS` requests, the request is held for a person.

Every department gets the read tools over its own records. A department filing a proposal also
gets `ask_department` and its playbook's `file_proposal`. `consult` runs another department on
one question with its read tools only, and returns its text answer as the result of
`ask_department`. A request may consult `MAX_CONSULTS` times.

The playbooks are read from `playbooks` when the module loads. Each file's `## Changes` section
is the playbook's dated history for staff and never reaches the prompt.
"""

import dataclasses

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from utility_agents import model, prompts, proposal, tools, trace
from utility_agents.config import PACKAGE
from utility_agents.schema import strict_object
from utility_agents.text import words
from utility_agents.work import Context, Handoff, Worked

MAX_TURNS = 8
MAX_CONSULTS = 1
NUDGE = "You have not filed a proposal. Call file_proposal now."
RULES = prompts.DEPARTMENT_RULES + "\n\n" + prompts.CONCERN_RULES


def _playbook_text(playbook: str) -> str:
    text = (PACKAGE / "playbooks" / f"{playbook}.md").read_text()

    return text.split("\n## Changes")[0].strip()


PLAYBOOKS = {playbook: _playbook_text(playbook) for playbook in proposal.PLAYBOOKS}


def run(handoff: Handoff, context: Context) -> Worked:
    """Works a handoff under `context`, which names the request, the playbook, the day and
    the models. Returns the proposal or the reason the request is held."""
    context = dataclasses.replace(
        context,
        department=proposal.department(context.playbook),
        message=handoff.message,
        mode="propose",
        consults_left=MAX_CONSULTS,
    )

    return _loop(context, _propose_prompt(context), _handoff_text(handoff, context))


def consult(department: str, question: str, context: Context) -> str:
    """The answer of `department` to another department's question."""
    context = dataclasses.replace(context, department=department, mode="consult")
    worked = _loop(context, _consult_prompt(context), prompts.evidence(question))

    if worked.answer is None:
        raise tools.ToolError(f"The consulted department did not answer: {worked.held_reason}")

    return worked.answer


def _loop(context: Context, system: str, text: str) -> Worked:
    definitions = tools.definitions(_offered(context), context)
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

            if call["name"] == tools.FILE_PROPOSAL.name:
                if corrected:
                    return Worked(steps, held_reason=failure)

                corrected = True

            if call["name"] == ASK_DEPARTMENT.name:
                context = dataclasses.replace(
                    context, consults_left=max(context.consults_left - 1, 0)
                )

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
def _called(call: dict, context: Context) -> tuple[object, str | None, dict]:
    def attempt() -> tuple[object, str | None]:
        try:
            return tools.call(_offered(context), call["name"], call["args"], context), None
        except tools.ToolError as error:
            return None, str(error)

    (result, failure), step = trace.timed(call["name"], attempt)
    step["input"] = None if call["name"] == tools.FILE_PROPOSAL.name else call["args"]
    step["result"] = "ok" if failure is None else failure

    if call["name"] == ASK_DEPARTMENT.name and failure is None:
        step["answer"] = result

    return result, failure, step


def _tool_message(call: dict, result: object, failure: str | None) -> ToolMessage:
    if failure is None:
        return ToolMessage(content=str(result), tool_call_id=call["id"])

    return ToolMessage(content=failure, tool_call_id=call["id"], status="error")


def _ask_department(arguments: dict, context: Context) -> str:
    if context.consults_left == 0:
        raise tools.ToolError(
            "No consults left for this request. File your proposal with what you have."
        )

    asked, others = arguments["department"], _others(context)

    if asked not in others:
        raise tools.ToolError(f"{asked} is not a department you can ask: {', '.join(others)}.")

    return consult(asked, arguments["question"], context)


def _others(context: Context) -> list[str]:
    return [name for name in proposal.DEPARTMENTS if name != context.department]


ASK_DEPARTMENT = tools.Tool(
    "ask_department",
    "Ask another department one question about records only it can read, such as an "
    "invoice or an asset. It answers from its records in text; it cannot act.",
    lambda context: strict_object(
        {
            "department": {"type": "string", "enum": _others(context)},
            "question": {"type": "string"},
        },
        ["department", "question"],
    ),
    _ask_department,
)


def _offered(context: Context) -> list[tools.Tool]:
    read_tools = tools.read_tools(context.department)

    if context.mode == "consult":
        return read_tools

    return [*read_tools, ASK_DEPARTMENT, tools.FILE_PROPOSAL]


def _propose_prompt(context: Context) -> str:
    return f"{_identity(context)}\n\n{RULES}\n\n{PLAYBOOKS[context.playbook]}"


def _consult_prompt(context: Context) -> str:
    return _identity(context) + "\n\n" + prompts.CONSULT_RULES


def _identity(context: Context) -> str:
    return (
        f"You are the {words(context.department)} agent of a regional electricity utility. "
        f"Today is {context.today}."
    )


def _handoff_text(handoff: Handoff, context: Context) -> str:
    return (
        f"Request {context.request_id}\n"
        f"Customer: {handoff.customer_id or 'not given'}\n"
        f"Intent: {handoff.intent}\n"
        f"Already tried: {handoff.tried}\n"
        "\n"
        f"{prompts.evidence(handoff.message)}\n"
    )
