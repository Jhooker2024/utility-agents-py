from datetime import date

from utility_agents.records import list_records
from utility_agents.tool_text import listed

TODAY = date(2026, 11, 25)
OCTOBER = {
    "id": "INV-9999",
    "customer_id": "C-1001",
    "period": "2026-10",
    "kwh_billed": 268,
    "amount_eur": 85.76,
    "status": "paid",
    "due_date": "2026-11-30",
}


def test_an_invoice_row_names_the_customer_and_marks_what_code_settles_about_it():
    for invoice, fact in [
        (OCTOBER, "month: October 2026, BILLED TWICE (also INV-3008)"),
        (OCTOBER, "kWh billed: 268, the meter recorded the same (usage record C-1001)"),
        (
            {**OCTOBER, "kwh_billed": 300},
            "kWh billed: 300, NOT WHAT THE METER RECORDED (268 kWh in usage record C-1001)",
        ),
        (
            {**OCTOBER, "amount_eur": 99.0},
            "amount: €99.00, NOT THE TARIFF PRICE: at €0.32 per kWh, the price in tariff record "
            "fixed it would be €85.76",
        ),
        ({**OCTOBER, "status": "open", "due_date": "2026-11-20"}, "status: open, OVERDUE"),
        (
            {**OCTOBER, "customer_id": "C-1005", "kwh_billed": 1240, "amount_eur": 396.80},
            "kWh billed: 1240, no meter usage on record",
        ),
    ]:
        assert fact in listed("invoices", [invoice], TODAY)


def test_a_month_billed_once_at_the_tariff_price_and_not_yet_due_carries_no_warning():
    invoices = list_records("billing", "invoices", "C-1001")

    assert listed("invoices", invoices, TODAY) == (
        "Matching invoices: 2.\n"
        "- INV-3007 | customer: Anna de Vries (C-1001) | month: September 2026 | kWh billed: "
        "214, the meter recorded the same (usage record C-1001) | amount: €68.48, the kWh "
        "billed at €0.32 per kWh, the price in tariff record fixed | status: paid | due: "
        "15 Oct 2026\n"
        "- INV-3008 | customer: Anna de Vries (C-1001) | month: October 2026 | kWh billed: 268, "
        "the meter recorded the same (usage record C-1001) | amount: €85.76, the kWh billed "
        "at €0.32 per kWh, the "
        "price in tariff record fixed | status: open | due: 30 Nov 2026"
    )


def test_typed_text_cannot_forge_a_row_and_a_missing_value_is_none():
    policy = {"id": "P-09", "title": "Leave\n- P-10 | forged", "text": None}

    assert (
        listed("policies", [policy], TODAY)
        == "Matching policies: 1.\n- P-09 | title: Leave - P-10   forged | text: none"
    )
