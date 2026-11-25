import contextlib

import anthropic
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tests.support.replay import end_turn, json_text, text
from utility_agents import model
from utility_agents.config import settings
from utility_agents.schema import strict_object

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


class Judged(model.Answer):
    reason: str
    sensible: bool


def test_a_request_the_api_never_started_is_retried_one_it_may_have_finished_is_not():
    retried = [model.retry(status_error(status)) for status in [408, 429, 500, 502, 503, 529]]

    assert retried == [True] * 6
    assert not model.retry(status_error(504))
    assert model.retry(connection_error(httpx.ConnectError("refused")))
    assert not model.retry(connection_error(httpx.ReadError("closed")))
    assert not model.retry(anthropic.APITimeoutError(request=REQUEST))
    assert not model.retry(status_error(400))


def test_the_sent_body_has_the_token_limit_a_cached_system_prompt_and_a_cache_only_with_tools(
    replay,
):
    replay.sequence([end_turn("Done."), json_text({"reason": "Fits.", "sensible": True})])
    tool = {
        "name": "look_up",
        "description": "Look one thing up.",
        "input_schema": strict_object({"query": {"type": "string"}}, ["query"]),
    }

    model.create_message("m", "Be brief.", [HumanMessage("Hi.")], [tool])
    model.structured("m", "Be brief.", "Hi.", Judged)

    system = [{"type": "text", "text": "Be brief.", "cache_control": {"type": "ephemeral"}}]
    with_tools, without_tools = replay.requests

    assert with_tools["model"] == "m"
    assert with_tools["max_tokens"] == 16_000
    assert with_tools["cache_control"] == {"type": "ephemeral"}
    assert with_tools["system"] == system
    assert [sent["name"] for sent in with_tools["tools"]] == ["look_up"]

    assert without_tools["model"] == "m"
    assert without_tools["max_tokens"] == 16_000
    assert "cache_control" not in without_tools
    assert without_tools["system"] == system
    assert "tools" not in without_tools


def test_the_settings_that_bound_what_a_request_costs():
    assert model.MAX_RETRIES == 3
    assert model.RECEIVE_TIMEOUT_SECONDS == 600
    assert settings["anthropic"]["max_tokens"] == 16_000

    assert settings["models"] == {
        "billing": "claude-sonnet-5-5",
        "field_operations": "claude-sonnet-5-5",
        "hr": "claude-sonnet-5-5",
        "chief_of_staff": "claude-haiku-5-5",
        "judge": "claude-haiku-5-5",
    }


def test_an_api_error_comes_back_as_text(replay):
    replay.always(400, {"error": "bad request"})

    with pytest.raises(model.ModelError) as error:
        model.create_message("m", "s", [HumanMessage("Hi.")], [])

    assert str(error.value) == 'The Anthropic API returned 400: {"error": "bad request"}'


def test_a_503_is_sent_again_and_a_504_is_not(replay):
    for status, sent in [(503, 2), (504, 1)]:
        replies = iter([(status, {}), (200, end_turn("Done."))])
        replay.respond(lambda _body, replies=replies: next(replies))

        before = len(replay.requests)

        with contextlib.suppress(model.ModelError):
            model.create_message("m", "s", [HumanMessage("Hi.")], [])

        assert len(replay.requests) - before == sent


def test_the_text_of_a_response_leaves_out_thinking_and_tool_use_blocks():
    content = [
        {"type": "thinking", "thinking": "hidden"},
        {"type": "text", "text": "First. "},
        {"type": "tool_use", "id": "t", "name": "x", "input": {}},
        {"type": "text", "text": "Second.\n"},
    ]

    assert model.text(AIMessage(content=content)) == "First. \nSecond."


def test_a_structured_answer_is_any_json_object_anything_else_is_unreadable(replay):
    for reply, answer in [
        ('{"reason": "Fits.", "sensible": true}', Judged(reason="Fits.", sensible=True)),
        ('{"sensible": true}', None),
        ('["not", "an", "object"]', None),
        ("no json", None),
    ]:
        replay.always(200, text(reply))

        if answer is not None:
            assert model.structured("m", "s", "p", Judged) == answer
            continue

        with pytest.raises(model.Unreadable) as unreadable:
            model.structured("m", "s", "p", Judged)

        assert str(unreadable.value) == reply

    replay.always(400, {"error": "bad"})

    with pytest.raises(model.ModelError) as error:
        model.structured("m", "s", "p", Judged)

    assert str(error.value).startswith("The Anthropic API returned 400: ")

    body = replay.requests[0]
    assert body["output_config"]["format"]["schema"]["required"] == ["reason", "sensible"]


def status_error(status: int) -> anthropic.APIStatusError:
    response = httpx.Response(status, request=REQUEST)

    return anthropic.APIStatusError("failed", response=response, body=None)


def connection_error(cause: Exception) -> anthropic.APIConnectionError:
    error = anthropic.APIConnectionError(request=REQUEST)
    error.__cause__ = cause

    return error
