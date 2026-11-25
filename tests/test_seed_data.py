"""The made-up records can answer what the screens invite: every customer has two bills and the
meter usage behind them, and every bill follows from its tariff and its meter reading, except
the one bill that is estimated on purpose.
"""

from datetime import date

from utility_agents import tool_text
from utility_agents.records import customer_by_email, list_records, lookup, search_customers

TODAY = date(2026, 11, 25)
ESTIMATED = "INV-3002"
CUSTOMERS = list_records("billing", "customers", None)
INVOICES = list_records("billing", "invoices", None)


def test_every_customer_has_two_invoices_a_tariff_a_meter_and_usage_for_each_billed_month():
    assert len(CUSTOMERS) == 10

    for customer in CUSTOMERS:
        invoices = list_records("billing", "invoices", customer["id"])
        [usage] = list_records("billing", "usage", customer["id"])
        assets = list_records("field_operations", "assets", customer["id"])
        billed = {invoice["period"] for invoice in invoices}
        unmetered = billed - set(usage["months"])

        assert [invoice["period"] for invoice in invoices if invoice["id"]] and len(invoices) == 2
        assert billed == {"2026-09", "2026-10"}, customer["id"]
        assert lookup("billing", "tariffs", customer["tariff"]) is not None
        assert any(asset["type"].endswith("meter") for asset in assets), customer["id"]
        assert unmetered == ({"2026-10"} if customer["id"] == "C-1005" else set()), customer["id"]
        assert set(usage["same_month_last_year"]) == {"2026-10"}
        assert customer_by_email(customer["email"]) == customer


def test_every_invoice_matches_its_tariff_and_its_meter_reading_except_the_estimated_one():
    assert len(INVOICES) == 20

    for invoice in INVOICES:
        [row] = tool_text.listed("invoices", [invoice], TODAY).split("\n")[1:]
        customer = lookup("billing", "customers", invoice["customer_id"])
        tariff = lookup("billing", "tariffs", customer["tariff"])
        [usage] = list_records("billing", "usage", invoice["customer_id"])
        metered = usage["months"].get(invoice["period"])

        assert invoice["amount_eur"] == round(
            invoice["kwh_billed"] * tariff["price_per_kwh_eur"], 2
        )
        assert "NOT THE TARIFF PRICE" not in row and "BILLED TWICE" not in row, invoice["id"]

        if invoice["id"] == ESTIMATED:
            assert metered is None
            assert "no meter usage on record" in row
            assert "Estimated reading" in invoice["note"]
        else:
            assert metered == invoice["kwh_billed"], invoice["id"]
            assert f"the meter recorded the same (usage record {customer['id']})" in row
            assert "note" not in invoice


def test_every_customer_is_found_by_name_and_by_street_and_number_with_their_meter():
    for customer in CUSTOMERS:
        street_and_number = customer["address"].split(",")[0]

        for query in (customer["name"], street_and_number):
            [match] = search_customers("field_operations", query)

            assert match.customer == customer
            assert match.assets
