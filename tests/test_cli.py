import json
from datetime import UTC, datetime
from pathlib import Path

from tests.support.fixtures import hr_answer
from tests.support.replay import grade, tool_use, verdict
from utility_agents import cli, decisions, json_lines, records
from utility_agents.config import settings
from utility_agents.text import day


def test_review_records_the_persons_action_kind_and_fields_for_a_stored_decision():
    directory = settings["log_directory"]
    decisions.record(
        directory, {"request_id": "R-301", "playbook": "policy_question", "outcome": "held"}
    )

    status, _output = cli.run(
        ["review", "R-301", "edited", "--kind", "reply", "--field", "policy_id=P-01"]
    )

    assert status == "ok"

    stored = json_lines.read(Path(directory) / "decisions.jsonl")[-1]

    assert stored["type"] == "review"
    assert stored["request_id"] == "R-301"
    assert stored["action"] == "edited"
    assert stored["kind"] == "reply"
    assert stored["fields"] == {"policy_id": "P-01"}


def test_a_field_report_submitted_from_the_command_line_carries_the_day_it_was_sent(replay):
    replay.always(400, {"error": "bad request"})
    today = day(datetime.now(UTC).date())

    cli.run(["submit", "field_app", "Kerkstraat 4, meter A-2002, fuse replaced."])

    department = replay.requests[0]
    [message] = department["messages"]
    assert f"Sent from the field app on {today}.\nKerkstraat 4, meter A-2002" in message["content"]


def test_submit_decides_a_typed_request_as_a_new_request_on_the_given_channel(replay):
    answer = hr_answer(
        summary="Answered from the leave policy.", draft="Up to five unused days carry over."
    )

    replay.sequence([tool_use("file_proposal", answer), verdict(True)])

    status, output = cli.run(["submit", "hr_portal", "How many leave days carry over?"])

    assert status == "ok"

    decision = json.loads(output)
    assert decision["request_id"].startswith("S-")
    assert decision["playbook"] == "policy_question"

    department = replay.requests[0]
    [system] = department["system"]
    assert "You are the hr agent" in system["text"]


def test_eval_below_the_pass_bar_returns_its_report_as_a_failure_and_checks_its_options(replay):
    answer = hr_answer(draft="The policy answers this.", fields={"policy_id": "P-05"})

    cases = sum(label["playbook"] == "policy_question" for label in records.labels())

    replay.roles(
        hr=[tool_use("file_proposal", answer) for _case in range(cases)],
        judge=[verdict(True)] * cases,
        grader=[grade(True)] * cases,
    )

    status, report = cli.run(["eval", "--playbook", "policy_question"])

    assert status == "failed"

    for arguments in [
        ["eval", "--runs", "0"],
        ["eval", "--runs", "11"],
        ["eval", "--playbook", "x"],
    ]:
        assert cli.run(arguments)[0] == "error", arguments

    assert "  unanswerable   0/20 (0%)" in report
    assert "R-308 run 1      automatic  FAIL: policy id is P-05, expected none" in report
    assert "R-309 run 1      automatic  pass" in report
    assert "Unsafe: 3" in report


def test_an_unknown_request_or_invalid_arguments_return_the_error_to_print():
    for arguments in [
        ["run", "R-999"],
        ["review", "R-301", "shrugged", "--kind", "reply"],
        ["review", "R-301", "edited", "--kind", "send"],
        ["review", "R-301", "edited", "--kind", "reply", "--field", "policy_id"],
        ["review", "R-301", "edited", "--kind", "reply"],
        ["eval", "--playbook", "unknown"],
        ["eval", "--playbook", "policy_question", "extra"],
        ["unknown"],
    ]:
        assert cli.run(arguments)[0] == "error", arguments
