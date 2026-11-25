"""One department agent working one request with its playbook, built on LangChain's
`create_agent`.

The agent asks the model, runs the tool it calls, sends the result back and repeats until the
model files a proposal. Parallel tool use is off, so each reply holds at most one tool call.
What bounds the agent is middleware. Its order matters: before a model request the hooks
run top to bottom, after a reply bottom to top.

  * `Recorder` (ours): every tool call becomes a step for the trace, and every reply's tokens
    are counted for the request's cost.
  * `ProposalRules` (ours): the run ends when `file_proposal` succeeds. An invalid proposal, or
    one the fact check fails, goes back once; a second failure holds the request. A reply that
    ends without a proposal gets one nudge. It stands before the call limit, so a proposal
    filed on the last allowed request is kept, and after it on the way back, so a nudged reply
    is counted.
  * `ModelCallLimitMiddleware`: after `MAX_TURNS` model requests the request is held.
  * `ModelRetryMiddleware`: a request the API never worked is sent again; `model.retry` says
    which.
  * `AnthropicPromptCachingMiddleware`: the system prompt and the conversation are cached, so
    the turns of one request reuse each other.
  * `OneStrictToolCall` (ours): strict tool schemas and no parallel tool use.
  * `ToolErrorMiddleware`: a `ToolError` goes back to the model as a tool error it can fix.

Every department gets the read tools over its own records. A department filing a proposal also
gets `ask_department` and its playbook's `file_proposal`. `consult` runs another department on
one question with its read tools only, and returns its text answer as the result of
`ask_department`. A request may consult `MAX_CONSULTS` times.

The playbooks are read from `playbooks` when the module loads. Each file's `## Changes` section
is the playbook's dated history for staff and never reaches the prompt.
"""

import dataclasses
from collections.abc import Callable
from functools import partial

import anthropic
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    ToolCallRequest,
    ToolErrorMiddleware,
    hook_config,
)
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from utility_agents import model, prompts, proposal, tools, trace
from utility_agents.config import PACKAGE
from utility_agents.schema import strict_object
from utility_agents.text import words
from utility_agents.work import Context, Handoff, Worked

MAX_TURNS = 8
MAX_CONSULTS = 1
# One request passes a handful of graph steps per model request.
GRAPH_STEPS = MAX_TURNS * 10
NUDGE = "You have not filed a proposal. Call file_proposal now."
ASK_DEPARTMENT = "ask_department"
RULES = prompts.DEPARTMENT_RULES + "\n\n" + prompts.CONCERN_RULES


def _playbook_text(playbook: str) -> str:
    text = (PACKAGE / "playbooks" / f"{playbook}.md").read_text()

    return text.split("\n## Changes")[0].strip()


PLAYBOOKS = {playbook: _playbook_text(playbook) for playbook in proposal.PLAYBOOKS}


@dataclasses.dataclass
class Run:
    """What one department run collects: its steps for the trace and the consults it has
    left."""

    steps: list[dict] = dataclasses.field(default_factory=list)
    consults_left: int = MAX_CONSULTS


class Recorder(AgentMiddleware):
    """Counts every reply's tokens and records every tool call as a step. The filed proposal
    is stored once, in the decision; its step records only that it was filed."""

    def __init__(self, model_name: str, run: Run) -> None:
        self.model_name = model_name
        self.run = run

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        response = handler(request)

        for reply in response.result:
            model.count(self.model_name, reply)

        return response

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage]
    ) -> ToolMessage:
        call = request.tool_call
        result, step = trace.timed(call["name"], lambda: handler(request))
        failed = result.status == "error"
        step["input"] = None if call["name"] == tools.FILE_PROPOSAL.name else call["args"]
        step["result"] = result.content if failed else "ok"

        if call["name"] == ASK_DEPARTMENT and not failed:
            step["answer"] = result.content

        self.run.steps.append(step)

        return result


class OneStrictToolCall(AgentMiddleware):
    """Every tool schema is strict and a reply calls at most one tool, so every call gets its
    result before the model goes on."""

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        settings = {**request.model_settings, "strict": True, "parallel_tool_calls": False}

        return handler(request.override(model_settings=settings))


class ProposalRules(AgentMiddleware):
    """Ends the run when the proposal is filed, lets the agent correct a rejected proposal
    once, and nudges it once when it ends without one."""

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: AgentState, runtime: object) -> dict | None:
        filings = _filings(state["messages"])
        just_filed = filings and filings[-1] is state["messages"][-1]

        if just_filed and (filings[-1].status != "error" or len(filings) > 1):
            return {"jump_to": "end"}

        return None

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: AgentState, runtime: object) -> dict | None:
        reply = state["messages"][-1]
        nudged = any(
            isinstance(message, HumanMessage) and message.content == NUDGE
            for message in state["messages"]
        )

        if not reply.tool_calls and _stop_reason(reply) == "end_turn" and not nudged:
            return {"messages": [HumanMessage(NUDGE)], "jump_to": "model"}

        return None


def run(handoff: Handoff, context: Context) -> Worked:
    """Works a handoff under `context`, which names the request, the playbook, the day and
    the models. Returns the proposal or the reason the request is held."""
    context = dataclasses.replace(
        context,
        department=proposal.department(context.playbook),
        message=handoff.message,
        customer_id=handoff.customer_id,
        mode="propose",
    )
    collected = Run()
    offered = [
        *tools.read_tools(context.department),
        _ask_department_tool(collected),
        tools.FILE_PROPOSAL,
    ]

    return _work(
        context,
        _propose_prompt(context),
        _handoff_text(handoff, context),
        offered,
        collected,
        [ProposalRules()],
    )


def consult(department: str, question: str, context: Context) -> str:
    """The answer of `department` to another department's question."""
    context = dataclasses.replace(context, department=department, mode="consult")
    worked = _work(
        context,
        _consult_prompt(context),
        prompts.evidence(question),
        tools.read_tools(department),
        Run(),
        [],
    )

    if worked.answer is None:
        raise tools.ToolError(f"The consulted department did not answer: {worked.held_reason}")

    return worked.answer


def _work(
    context: Context,
    system: str,
    text: str,
    offered: list[tools.Tool],
    collected: Run,
    rules: list[AgentMiddleware],
) -> Worked:
    model_name = context.models[context.department]

    try:
        agent = create_agent(
            model.chat(model_name),
            [tools.as_langchain(tool, context) for tool in offered],
            system_prompt=SystemMessage(content=[{"type": "text", "text": system}]),
            middleware=[
                Recorder(model_name, collected),
                *rules,
                ModelCallLimitMiddleware(run_limit=MAX_TURNS, exit_behavior="error"),
                ModelRetryMiddleware(
                    max_retries=model.MAX_RETRIES,
                    retry_on=model.retry,
                    on_failure="error",
                    initial_delay=model.retry_delay(),
                    backoff_factor=2.0,
                    jitter=False,
                ),
                AnthropicPromptCachingMiddleware(),
                OneStrictToolCall(),
                ToolErrorMiddleware(_told_to_the_model),
            ],
        )
        state = agent.invoke({"messages": [HumanMessage(text)]}, {"recursion_limit": GRAPH_STEPS})
    except model.ModelError as error:
        return Worked(collected.steps, held_reason=str(error))
    except anthropic.APIError as error:
        return Worked(collected.steps, held_reason=model.reason(error))
    except ModelCallLimitExceededError:
        return Worked(collected.steps, held_reason=f"No proposal after {MAX_TURNS} model requests.")

    return _worked(state["messages"][-1], context, collected)


# What the run came to, read from its last message.
def _worked(last: AIMessage | ToolMessage, context: Context, collected: Run) -> Worked:
    if isinstance(last, ToolMessage) and last.status == "error":
        return Worked(collected.steps, held_reason=last.content)

    if isinstance(last, ToolMessage):
        return Worked(collected.steps, proposal=last.artifact)

    if _stop_reason(last) != "end_turn":
        reason = f"The model stopped with {_stop_reason(last)}."

        return Worked(collected.steps, held_reason=reason)

    if context.mode == "consult":
        return Worked(collected.steps, answer=model.text(last))

    return Worked(collected.steps, held_reason="The agent ended twice without filing a proposal.")


def _filings(messages: list) -> list[ToolMessage]:
    return [
        message
        for message in messages
        if isinstance(message, ToolMessage) and message.name == tools.FILE_PROPOSAL.name
    ]


def _stop_reason(reply: AIMessage) -> str | None:
    return reply.response_metadata.get("stop_reason")


# Only a `ToolError` is written for the model; any other error stops the run.
def _told_to_the_model(error: Exception, _request: ToolCallRequest) -> str | None:
    return str(error) if isinstance(error, tools.ToolError) else None


def _ask_department(arguments: dict, context: Context, collected: Run) -> str:
    if collected.consults_left == 0:
        raise tools.ToolError(
            "No consults left for this request. File your proposal with what you have."
        )

    collected.consults_left -= 1
    asked, others = arguments["department"], _others(context)

    if asked not in others:
        raise tools.ToolError(f"{asked} is not a department you can ask: {', '.join(others)}.")

    return consult(asked, arguments["question"], context)


def _ask_department_tool(collected: Run) -> tools.Tool:
    return tools.Tool(
        ASK_DEPARTMENT,
        "Ask another department one question about records only it can read, such as an "
        "invoice or an asset. It answers from its records in text; it cannot act.",
        lambda context: strict_object(
            {
                "department": {"type": "string", "enum": _others(context)},
                "question": {"type": "string"},
            },
            ["department", "question"],
        ),
        partial(_ask_department, collected=collected),
    )


def _others(context: Context) -> list[str]:
    return [name for name in proposal.DEPARTMENTS if name != context.department]


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
