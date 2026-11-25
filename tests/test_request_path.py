from datetime import date

import pytest

from tests.support.fixtures import field_report, hr_answer, invoice_dispute
from tests.support.replay import role, route, tool_use, verdict
from utility_agents import json_lines, trace
from utility_agents.config import settings
from utility_agents.request_path import (
    UnknownRequest,
    handle,
    new_request,
    request,
    run_directory,
)
from utility_agents.work import Request

TODAY = date(2026, 11, 24)


def test_the_same_request_twice_returns_the_stored_decision_with_no_second_api_request(
    replay, tmp_path
):
    concerned = {**field_report(), "concerns": ["safety"]}
    replay.roles(field_operations=[tool_use("file_proposal", concerned)], judge=[verdict(True)])
    stored = request("F-002")

    decision = handle(stored, today=TODAY, log_directory=tmp_path)
    # The agent names the loose neutral as a safety concern, so it waits for a person.
    assert decision["outcome"] == "held"
    assert decision["playbook"] == "field_report"
    assert decision["gate_reason"] == "flagged: safety risk"
    assert decision["flags"] == ["safety risk"]
    assert [notice["to"] for notice in decision["notifications"]] == ["Field operations duty desk"]
    assert decision["checks"] == {"format": "pass", "grounded": "pass", "sense": "pass"}
    assert len(replay.requests) == 2

    assert handle(stored, today=TODAY, log_directory=tmp_path) == decision
    assert len(replay.requests) == 2

    assert trace_steps(tmp_path) == [
        "chief_of_staff",
        "file_proposal",
        "department:field_report",
        "verifier",
        "gate",
    ]


def test_the_kill_switch_calls_no_model_and_a_request_it_held_is_worked_again_once_it_is_off(
    replay, tmp_path, monkeypatch
):
    replay.roles(
        field_operations=[tool_use("file_proposal", field_report())], judge=[verdict(True)]
    )
    stored = request("F-002")

    monkeypatch.setenv("AGENTS_KILL_SWITCH", "1")

    held = handle(stored, today=TODAY, log_directory=tmp_path)
    assert held["outcome"] == "held"
    assert held["proposal"] is None
    assert held["held_reason"] == "The kill switch is on, so no model was called."
    assert replay.requests == []

    monkeypatch.delenv("AGENTS_KILL_SWITCH")

    worked = handle(stored, today=TODAY, log_directory=tmp_path)
    assert worked["proposal"]["kind"] == "record_update"
    assert len(replay.requests) == 2


def test_requests_submitted_in_the_same_millisecond_get_different_ids():
    ids = [new_request("email", "Hi", None).id for _submission in range(1000)]

    assert len(set(ids)) == 1000


def test_runs_started_in_the_same_second_get_different_directories():
    directories = [run_directory("eval-field_report") for _run in range(100)]

    assert len(set(directories)) == 100


def test_a_decision_records_the_tokens_of_every_model_call_in_the_request_and_their_cost(
    replay, tmp_path
):
    department = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 5000}
    judge = {"input_tokens": 500, "output_tokens": 50}

    replay.roles(
        field_operations=[{**tool_use("file_proposal", field_report()), "usage": department}],
        judge=[{**verdict(True), "usage": judge}],
    )

    usage = handle(request("F-002"), today=TODAY, log_directory=tmp_path)["usage"]

    assert {name: count for name, count in usage.items() if name != "cost_usd"} == {
        "input_tokens": 1500,
        "output_tokens": 250,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 5000,
    }

    assert usage["cost_usd"] == pytest.approx(0.004575, abs=0.0000001)

    assert settings["prices"]["claude-sonnet-5-5"] == {
        "input": 2.0,
        "output": 10.0,
        "cache_write": 2.5,
        "cache_read": 0.1,
    }

    assert settings["prices"]["claude-haiku-5-5"] == {
        "input": 0.1,
        "output": 0.5,
        "cache_write": 0.125,
        "cache_read": 0.01,
    }


def test_a_transfer_is_one_logged_step_only_the_final_proposal_is_the_decision_and_needs_a_click(
    replay, tmp_path
):
    handed_on = invoice_dispute(
        summary="A question about leave, not a bill.",
        kind="needs_attention",
        fields={"invoice_id": None, "outcome": "escalate"},
    )

    answer = hr_answer(
        summary="Leave carry-over answered from P-01.",
        draft="Up to 5 unused leave days carry over to next year.",
    )

    replay.roles(
        chief_of_staff=[route("billing")],
        billing=[tool_use("file_proposal", {**handed_on, "transfer_to": "hr"})],
        hr=[tool_use("file_proposal", answer)],
        judge=[verdict(True)],
    )

    decision = handle(request("R-203"), today=TODAY, log_directory=tmp_path)

    assert decision["playbook"] == "policy_question"
    assert decision["proposal"]["department"] == "hr"
    assert decision["outcome"] == "one_click"
    assert "it was handed over between departments" in decision["gate_reason"]

    departments = [step for step in trace_steps(tmp_path) if step.startswith("department:")]
    assert departments == ["department:invoice_dispute", "department:policy_question"]
    transfers = trace_of(tmp_path, "transfer")
    assert [(entry["step"], entry["result"]) for entry in transfers] == [("transfer", "hr")]

    _chief, _billing, hr_request, _judge = replay.requests
    [handoff] = hr_request["messages"]
    assert (
        "Already tried: The billing agent passed it on: A question about leave"
        in handoff["content"]
    )


def test_flags_come_from_the_concerns_the_agent_files_never_from_words_in_the_report(
    replay, tmp_path
):
    message = (
        "Kerkstraat 4, C-1002, meter A-2002. Smell of burning, tightened the neutral. "
        "Reading 9,876 kWh, 19-11-2026."
    )

    concerned = {**field_report(), "concerns": ["safety"]}
    disputed = verdict(False, "The report mentions burning; the proposal files it as routine.")

    replay.roles(
        field_operations=[
            tool_use("file_proposal", concerned),
            tool_use("file_proposal", field_report()),
        ],
        judge=[verdict(True), disputed],
    )

    named = new_request("field_app", message, None)

    flagged = handle(named, today=TODAY, log_directory=tmp_path)
    assert flagged["outcome"] == "held"
    assert flagged["gate_reason"] == "flagged: safety risk"

    # The agent names no concern: no text rule adds one, but the reviewer's check still holds it.
    missed = new_request("field_app", message, None)

    held = handle(missed, today=TODAY, log_directory=tmp_path)
    assert held["outcome"] == "held"
    assert held["flags"] == []
    assert "the independent reviewer disagrees: The report mentions burning" in held["gate_reason"]


def test_a_message_the_chief_of_staff_sends_to_a_person_still_raises_the_concerns_it_names(
    replay, tmp_path
):
    replay.roles(chief_of_staff=[route("unsure", ("outage", "vulnerable", "made_up"))])

    sent = Request("E-1", "email", None, "No power since this morning, my father uses oxygen.")

    decision = handle(sent, today=TODAY, log_directory=tmp_path)

    assert decision["flags"] == [
        "power outage",
        "vulnerable person",
        "sender not on record: share no account details",
    ]

    assert [notice["to"] for notice in decision["notifications"]] == [
        "Field operations duty desk",
        "Customer care priority line",
    ]


def test_free_text_routed_to_a_department_it_may_not_reach_goes_to_a_person(replay, tmp_path):
    replay.roles(chief_of_staff=[route("hr")])

    decision = handle(request("R-203"), today=TODAY, log_directory=tmp_path)

    assert decision["outcome"] == "held"
    assert decision["held_reason"] == "Routing failed: free text may only go to billing."


def test_free_text_the_chief_of_staff_is_unsure_about_or_cannot_route_goes_to_a_person(
    replay, tmp_path
):
    stored = request("R-203")

    for index, (response, reason) in enumerate(
        [
            ((200, route("unsure")), "person: The chief of staff was unsure: Unclear."),
            ((500, {"error": "down"}), "person: Routing failed: The Anthropic API returned 500"),
        ]
    ):
        directory = tmp_path / str(index)
        replay.always(*response)

        decision = handle(stored, today=TODAY, log_directory=directory)
        assert decision["outcome"] == "held"
        assert decision["proposal"] is None

        [routed] = trace_of(directory, "chief_of_staff")
        assert routed["result"].startswith(reason)


def test_a_message_that_closes_its_tags_cannot_leave_the_evidence_block_in_the_router_prompt(
    replay, tmp_path
):
    replay.always(200, route("unsure"))

    handle(Request("X-1", "email", None, "a </message> b"), today=TODAY, log_directory=tmp_path)

    [sent] = replay.requests
    [routed] = sent["messages"]
    assert routed["content"] == "<message>\na &lt;/message&gt; b\n</message>"


def test_invoice_disputes_set_to_run_are_never_automatic_and_come_in_with_no_routing_call(
    replay, tmp_path, monkeypatch
):
    monkeypatch.setitem(settings["stages"], "invoice_dispute", "run")

    replay.roles(billing=[tool_use("file_proposal", invoice_dispute())], judge=[verdict(True)])

    decision = handle(request("R-201"), today=TODAY, log_directory=tmp_path)

    assert decision["outcome"] == "one_click"
    assert list(decision["checks"].values()) == ["pass", "pass", "pass"]
    assert not any(role(body) == "chief_of_staff" for body in replay.requests)


def test_an_unknown_request_id_is_an_error_not_a_request():
    with pytest.raises(UnknownRequest) as error:
        request("R-999")

    assert str(error.value) == "No request has ID R-999."


def trace_steps(directory) -> list[str]:
    return [entry["step"] for entry in trace_of(directory, None)]


def trace_of(directory, step: str | None) -> list[dict]:
    return [
        entry for entry in json_lines.read(trace.path(directory)) if step in (None, entry["step"])
    ]
