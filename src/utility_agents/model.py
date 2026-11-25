"""The Claude models, through LangChain's `ChatAnthropic`.

`chat` builds the model a department agent runs on. `structured` asks one question whose answer
is a Pydantic model: the front door's route and the two judges' verdicts.

The kill switch (`AGENTS_KILL_SWITCH` set to anything but empty) stops every model call before
it is sent, so nothing is billed and every request is held with the reason.

A rate limit, an overloaded or failing server, a request the server timed out receiving
(status 408) or a connection that could not be opened is retried up to `MAX_RETRIES` times. A
timeout waiting for the reply, a gateway timeout (status 504) or a dropped connection is not:
the API may still finish and bill that request, so sending it again could pay twice. The SDK's
own retries are off, because they also retry those; `retry` is the one rule, used here and by
the agent's retry middleware. The wait for a reply is ten minutes, enough for the longest
answer the token limit allows.

The system prompt is always marked for the prompt cache. A structured answer is asked once, so
its conversation is not cached.

Sonnet 5.5 rejects a forced tool choice, which LangChain's default structured output uses, so
a structured answer uses the `json_schema` method.
"""

import json
import os
import time
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


def chat(model: str) -> ChatAnthropic:
    """The chat model for one model ID, or `ModelError` when no call may be made: the kill
    switch is on or the key is missing. The SDK's own retries are off; `retry` decides."""
    if os.environ.get(KILL_SWITCH_VARIABLE):
        raise ModelError("The kill switch is on, so no model was called.")

    if API_KEY_VARIABLE not in os.environ:
        raise ModelError(f"{API_KEY_VARIABLE} is not set.")

    api = settings["anthropic"]

    return ChatAnthropic(
        model=model,
        api_key=os.environ[API_KEY_VARIABLE],
        base_url=api["url"],
        max_tokens=api["max_tokens"],
        timeout=RECEIVE_TIMEOUT_SECONDS,
        max_retries=0,
        default_headers={"anthropic-version": api["version"]},
    )


def structured[Filled: Answer](
    model: str, system: str, prompt: str, answer: type[Filled]
) -> Filled:
    """Asks for one `answer`, which the API holds to its JSON schema. `Unreadable` when the
    reply is not one, as after a refusal or at the token limit."""
    asked = chat(model).with_structured_output(answer, method="json_schema", include_raw=True)
    cached_system = [{"type": "text", "text": system, "cache_control": CACHE_CONTROL}]
    reply = _invoke(asked, [SystemMessage(content=cached_system), HumanMessage(prompt)])
    count(model, reply["raw"])

    if reply["parsed"] is None:
        raise Unreadable(text(reply["raw"]))

    return reply["parsed"]


def count(model: str, reply: AIMessage) -> None:
    """Adds the tokens of one reply to the request's usage."""
    usage.add(model, reply.response_metadata.get("usage") or {})


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


def retry_delay() -> float:
    """Seconds before the first retry; each later retry waits twice as long."""
    return settings["anthropic"]["retry_delay_seconds"]


def reason(error: anthropic.APIError) -> str:
    """A failed request in words for the person who gets the request."""
    if isinstance(error, anthropic.APIStatusError):
        body = json.dumps(error.body, ensure_ascii=False)

        return f"The Anthropic API returned {error.status_code}: {body}"

    return str(error)


def _invoke(runnable: Any, prompt: list[BaseMessage]) -> Any:
    attempt = 0

    while True:
        try:
            return runnable.invoke(prompt)
        except anthropic.APIError as error:
            if attempt == MAX_RETRIES or not retry(error):
                raise ModelError(reason(error)) from error

        time.sleep(retry_delay() * 2**attempt)
        attempt += 1


# Whether the connection was never opened, so the request cannot have been sent.
def _never_connected(error: BaseException | None) -> bool:
    while error is not None:
        if isinstance(error, httpx.ConnectError):
            return True

        error = error.__cause__

    return False
