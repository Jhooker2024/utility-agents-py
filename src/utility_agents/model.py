"""One request to a Claude model, through LangChain's `ChatAnthropic`.

The kill switch (`AGENTS_KILL_SWITCH` set to anything but empty) stops every model call before
it is sent, so nothing is billed and every request is held with the reason.

A rate limit, an overloaded or failing server, a request the server timed out receiving
(status 408) or a connection that could not be opened is retried up to `MAX_RETRIES` times. A
timeout waiting for the reply, a gateway timeout (status 504) or a dropped connection is not:
the API may still finish and bill that request, so sending it again could pay twice. The SDK's
own retries are off, because they also retry those. The wait for a reply is ten minutes, enough
for the longest answer the token limit allows.

Prompt caching is on. The system prompt is always marked. A request with tools also marks the
conversation, so the turns of one question reuse each other; a request without tools, such as
the judge's, is asked once and would only pay to write a cache nobody reads.

Sonnet 5.5 rejects a forced tool choice and sampling parameters, so tools are bound with
`tool_choice="auto"` and strict schemas, and a structured answer uses the `json_schema` method.
"""

import json
import os
import time
from collections.abc import Callable
from typing import Any

import anthropic
import httpx
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from utility_agents import usage
from utility_agents.config import settings

API_KEY_VARIABLE = "ANTHROPIC_API_KEY"
KILL_SWITCH_VARIABLE = "AGENTS_KILL_SWITCH"
MAX_RETRIES = 3
RETRY_STATUSES = (408, 429, 500, 502, 503, 529)
RECEIVE_TIMEOUT_SECONDS = 600
CACHE_CONTROL = {"type": "ephemeral"}


# Pydantic adds a title to every model and field, and the class docstring as a description.
# The schema carries neither: what a model is told lives in the prompt.
def _bare(schema: dict) -> None:
    schema.pop("title", None)
    schema.pop("description", None)

    for field in schema.get("properties", {}).values():
        field.pop("title", None)


class Answer(BaseModel):
    """A structured answer: a model fills its fields in the order they are declared."""

    model_config = ConfigDict(json_schema_extra=_bare)


class ModelError(Exception):
    """A request that got no reply; the text says why."""


class Unreadable(Exception):
    """A reply that is not the structured answer asked for; the text is the reply."""


def create_message(
    model: str, system: str, messages: list[BaseMessage], tools: list[dict]
) -> AIMessage:
    """One turn of a conversation in which the model may call one of `tools`."""

    def bound(chat: ChatAnthropic) -> Any:
        return chat.bind_tools(tools, tool_choice="auto", strict=True, parallel_tool_calls=False)

    return _send(model, bound, system, messages, cache_control=CACHE_CONTROL)


def structured[Filled: Answer](
    model: str, system: str, prompt: str, answer: type[Filled]
) -> Filled:
    """Asks for one `answer`, which the API holds to its JSON schema. `Unreadable` when the
    reply is not one, as after a refusal or at the token limit."""

    def bound(chat: ChatAnthropic) -> Any:
        return chat.with_structured_output(answer, method="json_schema", include_raw=True)

    reply = _send(model, bound, system, [HumanMessage(prompt)])

    if reply["parsed"] is None:
        raise Unreadable(text(reply["raw"]))

    return reply["parsed"]


def text(message: AIMessage) -> str:
    """The text of a reply, without thinking or tool-use blocks."""
    if isinstance(message.content, str):
        return message.content.strip()

    blocks = [block["text"] for block in message.content if block.get("type") == "text"]

    return "\n".join(blocks).strip()


def retry(error: Exception) -> bool:
    """Whether a failed request is worth sending again. 529 is the API's overloaded status."""
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code in RETRY_STATUSES

    return _never_connected(error)


def _send(
    model: str,
    bound: Callable[[ChatAnthropic], Any],
    system: str,
    messages: list[BaseMessage],
    **options: Any,
) -> Any:
    if os.environ.get(KILL_SWITCH_VARIABLE):
        raise ModelError("The kill switch is on, so no model was called.")

    if API_KEY_VARIABLE not in os.environ:
        raise ModelError(f"{API_KEY_VARIABLE} is not set.")

    api = settings["anthropic"]
    chat = ChatAnthropic(
        model=model,
        api_key=os.environ[API_KEY_VARIABLE],
        base_url=api["url"],
        max_tokens=api["max_tokens"],
        timeout=RECEIVE_TIMEOUT_SECONDS,
        max_retries=0,
        default_headers={"anthropic-version": api["version"]},
    )
    cached_system = [{"type": "text", "text": system, "cache_control": CACHE_CONTROL}]
    prompt = [SystemMessage(content=cached_system), *messages]
    reply = _invoke(bound(chat), prompt, options)
    message = reply["raw"] if isinstance(reply, dict) else reply
    usage.add(model, message.response_metadata.get("usage") or {})

    return reply


def _invoke(runnable: Any, prompt: list[BaseMessage], options: dict, attempt: int = 0) -> Any:
    try:
        return runnable.invoke(prompt, **options)
    except anthropic.APIError as error:
        if attempt == MAX_RETRIES or not retry(error):
            raise ModelError(_reason(error)) from error

    time.sleep(settings["anthropic"]["retry_delay_seconds"] * 2**attempt)

    return _invoke(runnable, prompt, options, attempt + 1)


def _reason(error: anthropic.APIError) -> str:
    if isinstance(error, anthropic.APIStatusError):
        body = json.dumps(error.body, ensure_ascii=False)

        return f"The Anthropic API returned {error.status_code}: {body}"

    return str(error)


# Whether the connection was never opened, so the request cannot have been sent.
def _never_connected(error: BaseException | None) -> bool:
    while error is not None:
        if isinstance(error, httpx.ConnectError):
            return True

        error = error.__cause__

    return False
