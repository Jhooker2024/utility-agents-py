from utility_agents import json_lines, trace


def test_a_trace_is_one_json_line_per_step_with_the_request_id(tmp_path):
    result, step = trace.timed("department", lambda: "done")

    assert result == "done"

    trace.append(tmp_path, "F-001", [step, {"step": "gate", "result": "held", "milliseconds": 0}])

    lines = json_lines.read(trace.path(tmp_path))

    assert len(lines) == 2
    assert lines[0]["request_id"] == "F-001"
    assert lines[0]["step"] == "department"
    assert lines[1]["step"] == "gate"
    assert isinstance(lines[0]["milliseconds"], int)
