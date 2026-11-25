"""Tool results as labelled text, in the tellent agent's format: a count line, then one row per
record, `- ` and columns joined by ` | `, `label: value`, and `none` for a missing value. Names
stand next to IDs. What has one right answer is worked out here, so the model reads it instead
of deriving it, and a warning in capitals follows the value it is about, as tellent writes
`, OVERDUE`: a month billed twice, an amount that is not the kWh at the tariff's price, billed
kWh the meter did not record, and an open invoice past its due date.
"""

from datetime import date

from utility_agents import records
from utility_agents.text import day, decimals, month, words

ROW_PREFIX = "- "
COLUMN_SEPARATOR = " | "
NONE = "none"
LABELS = {
    "customers": "customers",
    "assets": "meters and cables",
    "invoices": "invoices",
    "usage": "usage records",
    "tariffs": "tariffs",
    "policies": "policies",
}


def listed(collection: str, found: list[dict], today: date) -> str:
    """Records of one collection, read on `today`: a count line, then one row each."""
    return _list(LABELS[collection], [_row(collection, record, today) for record in found])


def customers(matches: list[records.Match]) -> str:
    """Customers found by a search, each with their meters and cables."""
    return _list("customers", [_customer_row(match.customer, match.assets) for match in matches])


def _list(label: str, rows: list[str]) -> str:
    return "\n".join([f"Matching {label}: {len(rows)}.", *rows])


def _row(collection: str, record: dict, today: date) -> str:
    if collection == "customers":
        assets = records.list_records("field_operations", "assets", record["id"])

        return _customer_row(record, assets)

    if collection == "assets":
        return _columns(
            _text(record["id"]),
            f"type: {words(record['type'])}",
            f"location: {_text(record['location'])}",
            f"customer: {_owner(record['customer_id'])}",
        )

    if collection == "invoices":
        return _invoice_row(record, today)

    if collection == "usage":
        return _columns(
            f"customer: {_owner(record['id'])}",
            f"metered: {_months(record.get('months'))}",
            f"same month last year: {_months(record.get('same_month_last_year'))}",
            f"similar homes: {_months(record.get('similar_homes'))}",
            f"efficient homes: {_months(record.get('efficient_homes'))}",
        )

    if collection == "tariffs":
        return _columns(
            _text(record["id"]), f"price: €{decimals(record['price_per_kwh_eur'], 2)} per kWh"
        )

    return _columns(
        _text(record["id"]),
        f"title: {_text(record.get('title'))}",
        f"text: {_text(record.get('text'))}",
    )


def _invoice_row(invoice: dict, today: date) -> str:
    note = [f"note: {_text(invoice['note'])}"] if invoice.get("note") is not None else []

    return _columns(
        _text(invoice["id"]),
        f"customer: {_owner(invoice['customer_id'])}",
        f"month: {month(invoice['period'])}" + _twice(invoice),
        f"kWh billed: {invoice['kwh_billed']}" + _metered(invoice),
        f"amount: €{decimals(invoice['amount_eur'], 2)}" + _priced(invoice),
        f"status: {_text(invoice['status'])}" + _overdue(invoice, today),
        f"due: {day(date.fromisoformat(invoice['due_date']))}",
        *note,
    )


def _customer_row(customer: dict, assets: list[dict]) -> str:
    return _columns(
        _text(customer["name"]),
        f"id: {_text(customer['id'])}",
        f"address: {_text(customer['address'])}",
        f"email: {_text(customer['email'])}",
        f"tariff: {_text(customer['tariff'])}",
        f"meters and cables: {_assets_text(assets)}",
    )


def _columns(*columns: str) -> str:
    return ROW_PREFIX + COLUMN_SEPARATOR.join(columns)


# Line breaks and the column separator become a space, so typed text cannot forge a row.
def _text(value: object) -> str:
    if value is None:
        return NONE

    text = str(value).replace("\r\n", " ")

    for forging in ("\n", "\r", "|"):
        text = text.replace(forging, " ")

    return text


def _assets_text(assets: list[dict]) -> str:
    if not assets:
        return NONE

    return ", ".join(
        f"{asset['id']} {words(asset['type'])} at {_text(asset['location'])}" for asset in assets
    )


def _months(by_month: dict | None) -> str:
    if by_month is None:
        return NONE

    return ", ".join(f"{month(period)} {kwh} kWh" for period, kwh in sorted(by_month.items()))


def _twice(invoice: dict) -> str:
    others = [
        other["id"]
        for other in records.list_records("billing", "invoices", invoice["customer_id"])
        if other["period"] == invoice["period"] and other["id"] != invoice["id"]
    ]

    return f", BILLED TWICE (also {', '.join(others)})" if others else ""


def _metered(invoice: dict) -> str:
    recorded = [
        usage["months"][invoice["period"]]
        for usage in records.list_records("billing", "usage", invoice["customer_id"])
        if (usage.get("months") or {}).get(invoice["period"]) is not None
    ]

    if len(recorded) != 1:
        return ", no meter usage on record"

    if recorded[0] == invoice["kwh_billed"]:
        return ", the meter recorded the same"

    return f", NOT WHAT THE METER RECORDED ({recorded[0]} kWh)"


def _priced(invoice: dict) -> str:
    customer = records.lookup("billing", "customers", invoice["customer_id"])
    tariff = records.lookup("billing", "tariffs", customer["tariff"])
    expected = round(invoice["kwh_billed"] * tariff["price_per_kwh_eur"], 2)
    rate = decimals(tariff["price_per_kwh_eur"], 2)
    price = f"€{rate} per kWh, the price in tariff record {tariff['id']}"

    if expected == invoice["amount_eur"]:
        return f", the kWh billed at {price}"

    return f", NOT THE TARIFF PRICE: at {price} it would be €{decimals(expected, 2)}"


def _overdue(invoice: dict, today: date) -> str:
    if invoice["status"] == "open" and date.fromisoformat(invoice["due_date"]) < today:
        return ", OVERDUE"

    return ""


def _owner(customer_id: str | None) -> str:
    customer = records.lookup("billing", "customers", customer_id)

    if customer is None:
        return _text(customer_id)

    return f"{customer['name']} ({customer_id})"
