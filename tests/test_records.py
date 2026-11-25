from collections import Counter

import pytest

from utility_agents import flags, records


def test_a_department_reads_a_record_in_its_scope_and_nothing_outside_it():
    invoice = records.lookup("billing", "invoices", "INV-3002")
    assert invoice["id"] == "INV-3002"
    assert invoice["amount_eur"] == 396.8

    assert records.lookup("field_operations", "assets", "A-2001")["id"] == "A-2001"

    for department, collection in [
        ("billing", "policies"),
        ("hr", "customers"),
        ("field_operations", "invoices"),
        ("unknown", "customers"),
    ]:
        with pytest.raises(records.OutOfScope):
            records.lookup(department, collection, "P-01")


def test_a_missing_unparseable_or_unknown_id_is_no_match_never_another_record():
    for record_id in [None, "", 1001, "C-9999", " C-1001", "c-1001", ["C-1001"]]:
        assert records.lookup("billing", "customers", record_id) is None


def test_a_list_holds_only_the_departments_collection_and_only_the_given_customers_records():
    invoices = records.list_records("billing", "invoices", "C-1008")
    assert [invoice["id"] for invoice in invoices] == ["INV-3003", "INV-3004"]

    policies = records.list_records("hr", "policies", None)
    assert len(policies) == 5

    assert records.list_records("billing", "invoices", "C-9999") == []

    with pytest.raises(records.OutOfScope):
        records.list_records("field_operations", "invoices", "C-1008")


def test_listing_by_customer_finds_a_customers_usage_and_lists_collections_without_one_whole():
    assert [usage["id"] for usage in records.list_records("billing", "usage", "C-1004")] == [
        "C-1004"
    ]
    assert [
        customer["id"] for customer in records.list_records("billing", "customers", "C-1004")
    ] == ["C-1004"]

    tariffs = records.list_records("billing", "tariffs", "C-1004")
    assert len(tariffs) == 4


def test_a_customer_is_found_by_name_address_email_or_meter_with_their_assets():
    for query, expected in [
        ("Bram Jansen", ["C-1002"]),
        ("Anna Devries", ["C-1001"]),
        ("ANNA DE VRIES", ["C-1001"]),
        ("Yílmaz", ["C-1005"]),
        ("kerkstraat 4", ["C-1002"]),
        ("Anna.DeVries@example.com", ["C-1001"]),
        ("A-2008", ["C-1008"]),
        ("zwolle", ["C-1001", "C-1004", "C-1007"]),
        ("Jansen Molenweg", []),
        ("", []),
    ]:
        matches = records.search_customers("field_operations", query)
        assert [match.customer["id"] for match in matches] == expected, query

    [match] = records.search_customers("field_operations", "Mulder")
    assert sorted(asset["id"] for asset in match.assets) == ["A-2007", "A-2011"]

    with pytest.raises(records.OutOfScope):
        records.search_customers("hr", "Bram")


def test_an_email_address_identifies_one_customer_ignoring_case_and_spaces():
    assert records.customer_by_email(" Anna.DeVries@example.com ")["id"] == "C-1001"

    assert records.customer_by_email("someone@example.com") is None
    assert records.customer_by_email(None) is None


def test_requests_are_found_by_id_and_are_in_no_departments_scope():
    assert records.request("F-001")["channel"] == "field_app"
    assert records.request("F-999") is None

    with pytest.raises(records.OutOfScope):
        records.lookup("billing", "requests", "F-001")


def test_the_labelled_set_at_least_20_unanswerable_and_20_ambiguous_cases_per_playbook():
    labels = records.labels()

    counted = Counter((label["playbook"], label.get("category", "answerable")) for label in labels)

    assert counted == {
        ("field_report", "answerable"): 60,
        ("field_report", "unanswerable"): 20,
        ("field_report", "ambiguous"): 20,
        ("invoice_dispute", "answerable"): 33,
        ("invoice_dispute", "unanswerable"): 20,
        ("invoice_dispute", "ambiguous"): 20,
        ("policy_question", "answerable"): 33,
        ("policy_question", "unanswerable"): 20,
        ("policy_question", "ambiguous"): 20,
    }

    assert all(
        label.get("category", "answerable") == "answerable" or label["note"] for label in labels
    )

    assert all(set(label["flags"]) <= set(flags.CONCERNS) for label in labels)

    unmatched = [label for label in labels if records.request(label["request_id"]) is None]

    assert unmatched == []


def test_the_id_field_table_names_every_id_field_once_and_a_subset_may_only_name_those():
    assert list(records.ID_FIELDS) == ["customer_id", "asset_id", "invoice_id", "policy_id"]

    subset = records.id_fields(("asset_id", "customer_id"))
    assert list(subset) == ["asset_id", "customer_id"]
    assert subset["asset_id"].collection == "assets"
    assert subset["asset_id"].name == "meter or cable"

    report = records.report_fields()
    assert list(report) == ["customer_id", "asset_id"]
    assert report["asset_id"].short_name == "meter"

    with pytest.raises(ValueError) as raised:
        records.id_fields(("fault_type",))

    assert str(raised.value) == "fault_type is not an ID field"

    for record_id, known in [("A-2002", True), ("A-9999", False), (None, False)]:
        assert records.known("field_operations", "assets", record_id) == known
