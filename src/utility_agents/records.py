"""The utility's records, read from the hand-written JSON files in `seed` when the module loads.

A department reads only the collections in its scope. `lookup` returns the record, or None for
a missing, unparseable or unknown ID; `list_records` returns the records. Both raise
`OutOfScope` when the collection is outside the department's scope. Nothing here writes:
changing a record is what a proposal asks a person to do.

`request` and `labels` are the inputs and the staff decisions the eval stands in for. They are
not in any department's scope.
"""

import json
import unicodedata
from typing import NamedTuple

from utility_agents.config import PACKAGE

COLLECTIONS = ("customers", "assets", "invoices", "usage", "tariffs", "policies", "requests")
SEARCH_LIMIT = 5
DIGITS = "0123456789"
REPORT_FIELDS = ("customer_id", "asset_id")
CUSTOMER_FIELDS = {
    "customers": "id",
    "usage": "id",
    "assets": "customer_id",
    "invoices": "customer_id",
}
SCOPES = {
    "billing": ("customers", "invoices", "usage", "tariffs"),
    "field_operations": ("customers", "assets"),
    "hr": ("policies",),
}


class IdField(NamedTuple):
    """An ID field a proposal can hold: the collection its records are in, its name in a
    check's text, and the short name a menu shows."""

    collection: str
    name: str
    short_name: str


ID_FIELDS = {
    "customer_id": IdField("customers", "customer", "customer"),
    "asset_id": IdField("assets", "meter or cable", "meter"),
    "invoice_id": IdField("invoices", "invoice", "invoice"),
    "policy_id": IdField("policies", "policy", "policy"),
}


class OutOfScope(Exception):
    """A department asked for a collection it may not read."""


class Match(NamedTuple):
    customer: dict
    assets: list[dict]


def _load(name: str) -> list[dict]:
    return json.loads((PACKAGE / "seed" / f"{name}.json").read_text())


_BY_ID = {
    collection: {record["id"]: record for record in _load(collection)} for collection in COLLECTIONS
}
_LABELS = _load("labels")


def collections(department: str) -> tuple[str, ...]:
    """The collections a department may read."""
    return SCOPES.get(department, ())


def lookup(department: str, collection: str, record_id: object) -> dict | None:
    _scoped(department, collection)

    return _fetch(collection, record_id)


def known(department: str, collection: str, record_id: object) -> bool:
    """Whether `record_id` is a record of `collection` in the department's scope."""
    return collection in collections(department) and _fetch(collection, record_id) is not None


def id_fields(fields: tuple[str, ...]) -> dict[str, IdField]:
    """The table entries of `fields`, in that order; a field that is not an ID field is an
    error."""
    for field in fields:
        if field not in ID_FIELDS:
            raise ValueError(f"{field} is not an ID field")

    return {field: ID_FIELDS[field] for field in fields}


def report_fields() -> dict[str, IdField]:
    """The ID fields that say which customer and asset a field report is about."""
    return id_fields(REPORT_FIELDS)


def list_records(department: str, collection: str, customer_id: str | None) -> list[dict]:
    """Every record of a collection in scope. With a `customer_id`, only that customer's
    records of a collection that belongs to customers; a collection that does not, such as
    tariffs, is whole."""
    _scoped(department, collection)
    field = CUSTOMER_FIELDS.get(collection)
    records = [
        record
        for record in _BY_ID[collection].values()
        if customer_id is None or field is None or record[field] == customer_id
    ]

    return sorted(records, key=lambda record: record["id"])


def search_customers(department: str, query: str) -> list[Match]:
    """Customers in scope that match a search, with their assets: every word of the query must
    appear in the customer's ID, name, address or email, or in one of their assets' ID or
    location. Case, accents and punctuation are ignored. At most `SEARCH_LIMIT`, by ID."""
    _scoped(department, "customers")
    wanted = _words(query)
    matches = [
        match
        for match in map(_with_assets, _BY_ID["customers"].values())
        if wanted and all(word in _searchable(match) for word in wanted)
    ]

    return sorted(matches, key=lambda match: match.customer["id"])[:SEARCH_LIMIT]


def customer_by_email(email: object) -> dict | None:
    """The customer whose email address this is, ignoring case, or None."""
    if not isinstance(email, str):
        return None

    address = email.strip().lower()

    return next(
        (
            customer
            for customer in _BY_ID["customers"].values()
            if customer["email"].lower() == address
        ),
        None,
    )


def request(request_id: object) -> dict | None:
    return _fetch("requests", request_id)


def labels() -> list[dict]:
    return _LABELS


def _with_assets(customer: dict) -> Match:
    assets = [
        asset for asset in _BY_ID["assets"].values() if asset["customer_id"] == customer["id"]
    ]

    return Match(customer, assets)


# As in the tellent agent: case and accents do not count, and a query word may be part of a
# name, so "devries" finds "de Vries" and "ines" finds "Inês".
def _searchable(match: Match) -> str:
    customer = match.customer
    texts = [customer["id"], customer["name"], customer["address"], customer["email"]]

    for asset in match.assets:
        texts += [asset["id"], asset["location"]]

    return "".join(_words(" ".join(texts)))


def _words(text: str) -> list[str]:
    unaccented = "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if not unicodedata.combining(character)
    )

    return "".join(map(_word_character, unaccented.lower())).split()


# Letters, digits and hyphens make words; anything else separates them. A lowercased letter
# changes when uppercased; a digit or a sign does not.
def _word_character(character: str) -> str:
    if character == "-" or character in DIGITS or character.upper() != character:
        return character

    return " "


def _scoped(department: str, collection: str) -> None:
    if collection not in collections(department):
        raise OutOfScope(f"{collection} is outside the {department} department's records.")


def _fetch(collection: str, record_id: object) -> dict | None:
    if not isinstance(record_id, str):
        return None

    return _BY_ID[collection].get(record_id)
