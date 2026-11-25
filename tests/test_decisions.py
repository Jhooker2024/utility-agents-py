from datetime import date

import pytest

from utility_agents import decisions


def test_a_stored_decision_is_found_by_request_id_as_it_reads_back(tmp_path):
    stored = decisions.record(
        tmp_path,
        {
            "request_id": "F-001",
            "playbook": "field_report",
            "outcome": "automatic",
            "date": date(2026, 11, 24),
            "proposal": {"kind": "record_update"},
        },
    )

    assert decisions.find(tmp_path, "F-001") == stored
    assert stored["outcome"] == "automatic"
    assert stored["proposal"]["kind"] == "record_update"
    assert decisions.find(tmp_path, "F-002") is None


def test_a_review_needs_a_stored_decision(tmp_path):
    review = {"action": "rejected", "kind": "reply", "fields": {}, "date": date(2026, 11, 24)}

    with pytest.raises(decisions.NoDecision) as raised:
        decisions.review(tmp_path, "F-404", review)

    assert str(raised.value) == "No decision for F-404."


def test_rejected_review_of_an_automatic_decision_drops_the_playbook_one_stage_for_breach_window(
    tmp_path,
):
    decide(tmp_path, "F-001", "field_report", "automatic", date(2026, 11, 1))
    decide(tmp_path, "F-002", "field_report", "one_click", date(2026, 11, 1))
    decide(tmp_path, "R-301", "policy_question", "automatic", date(2026, 11, 1))
    review(tmp_path, "F-002", "rejected", date(2026, 11, 1))
    review(tmp_path, "R-301", "rejected", date(2026, 11, 1))

    assert decisions.stage(tmp_path, "field_report", "run", date(2026, 11, 24)) == "run"

    review(tmp_path, "F-001", "rejected", date(2026, 11, 1))

    assert decisions.stage(tmp_path, "field_report", "run", date(2026, 11, 24)) == "walk"
    assert decisions.stage(tmp_path, "field_report", "run", date(2026, 12, 1)) == "walk"
    assert decisions.stage(tmp_path, "field_report", "run", date(2026, 12, 2)) == "run"
    assert decisions.stage(tmp_path, "field_report", "walk", date(2026, 11, 24)) == "crawl"
    assert decisions.stage(tmp_path, "field_report", "crawl", date(2026, 11, 24)) == "crawl"


def test_the_cap_counts_only_automatic_decisions_on_the_given_day(tmp_path):
    decide(tmp_path, "F-001", "field_report", "automatic", date(2026, 11, 24))
    decide(tmp_path, "F-002", "field_report", "automatic", date(2026, 11, 23))
    decide(tmp_path, "F-003", "field_report", "one_click", date(2026, 11, 24))

    assert decisions.automatic_today(tmp_path, date(2026, 11, 24)) == 1
    assert decisions.automatic_today(tmp_path, date(2026, 11, 25)) == 0


def test_a_request_with_no_playbook_keeps_its_empty_stage_even_after_a_breach(tmp_path):
    decide(tmp_path, "F-001", "field_report", "automatic", date(2026, 11, 24))
    review(tmp_path, "F-001", "rejected", date(2026, 11, 24), "record_update", {})

    assert decisions.stage(tmp_path, None, None, date(2026, 11, 24)) is None
    assert decisions.stage(tmp_path, "field_report", "walk", date(2026, 11, 24)) == "crawl"


@pytest.mark.parametrize(
    ("stage", "lower", "higher"),
    [("crawl", "crawl", "walk"), ("walk", "crawl", "run"), ("run", "walk", "run")],
)
def test_stages_step_one_down_or_up_and_stop_at_crawl_and_run(stage, lower, higher):
    assert (decisions.lower(stage), decisions.higher(stage)) == (lower, higher)


def decide(directory, request_id, playbook, outcome, day):
    decisions.record(
        directory,
        {
            "request_id": request_id,
            "playbook": playbook,
            "outcome": outcome,
            "date": day,
            "proposal": {"kind": "record_update", "fields": {"follow_up": "none"}},
        },
    )


def review(directory, request_id, action, day, kind="record_update", fields=None):
    decisions.review(
        directory,
        request_id,
        {"action": action, "kind": kind, "fields": fields or {}, "date": day},
    )
