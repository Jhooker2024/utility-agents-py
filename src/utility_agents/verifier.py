"""Three independent checks on what a department returned. Each is None when it passes, or the
reason it fails.

  * format: the department filed a proposal that passed its schema, after the one corrective
    retry. A held request fails it with the reason it was held.
  * grounded: checked in code against the proposal's structured fields, never by searching the
    message for patterns. Every ID field matches a record in the department's scope. For a
    field report, each reading's quote appears in the report and holds the reading's digits,
    the visit date's quote appears in the report and names that date (or, with no quote, the
    visit date is today or left empty), and the note lists no commitment: a field report
    promises nothing. A meter or cable belongs to the customer named. For an invoice dispute,
    the invoice belongs to the customer the request is from, and the customer's words that
    identify it appear in the message; with no such words the invoice may be named only when
    it is the customer's only one. Every commitment's words appear in the draft and, except
    for a legal one, in its source: the message, or a fact its record's tool row shows,
    written the usual ways.
  * sense: a judge model sees only the message and the proposal, never the playbook or the
    agent's prompt, and says whether the proposal fits the message.

Text is compared lowercased with runs of whitespace as one space.
"""

from datetime import date

from utility_agents import json_lines, model, prompts, records, tool_text
from utility_agents.proposal import Commitment, FieldReport, InvoiceDispute, Proposal
from utility_agents.text import day, decimals, figure, grouped
from utility_agents.work import Context, Request, Worked

Check = str | None

MONTH_NAMES = (
    (("january", "jan"), ("januari",)),
    (("february", "feb"), ("februari",)),
    (("march", "mar"), ("maart", "mrt")),
    (("april", "apr"), ("april",)),
    (("may",), ("mei",)),
    (("june", "jun"), ("juni",)),
    (("july", "jul"), ("juli",)),
    (("august", "aug"), ("augustus",)),
    (("september", "sep", "sept"), ("september",)),
    (("october", "oct"), ("oktober", "okt")),
    (("november", "nov"), ("november",)),
    (("december", "dec"), ("december",)),
)
ORDINAL_SUFFIXES = ("", "st", "nd", "rd", "th", "e")
PERIOD_FIELD = "period"
NOTHING_TO_CHECK = "There is no proposal to check."


class Verdict(model.Answer):
    """The sense judge's answer, reason first so it reasons before it commits."""

    reason: str
    sensible: bool


def verify(worked: Worked, request: Request, context: Context) -> dict:
    """The three checks for what a department returned for a request."""
    if worked.proposal is None:
        return {
            "format": worked.held_reason,
            "grounded": NOTHING_TO_CHECK,
            "sense": NOTHING_TO_CHECK,
        }

    return {
        "format": None,
        "grounded": grounded(worked.proposal, request.message, context.today, request.customer_id),
        "sense": sense(worked.proposal, request.message, context.models["judge"], context.today),
    }


def grounded(
    proposal: Proposal, message: str, today: date, customer_id: str | None = None
) -> Check:
    """`customer_id` is the customer the request is from, when the channel knows it."""
    problems = [
        *_unmatched_ids(proposal),
        *_field_report_problems(proposal, message, today),
        *_invoice_problems(proposal, message, customer_id),
        *_commitment_problems(proposal, message),
    ]

    return " ".join(problems) or None


def sense(proposal: Proposal, message: str, judge: str, today: date) -> Check:
    try:
        verdict = model.structured(
            judge, prompts.SENSE_JUDGE, _judge_prompt(proposal, message, today), Verdict
        )
    except model.ModelError as error:
        return f"the judge request failed: {error}"
    except model.Unreadable:
        return "the judge gave no verdict"

    return None if verdict.sensible else verdict.reason


def proposal_json(proposal: dict | None) -> str:
    """A proposal as the JSON a judge reads, with `<` and `/` escaped so text inside it cannot
    close the proposal tags."""
    return json_lines.compact(proposal).replace("<", "\\u003C").replace("/", "\\/")


def _unmatched_ids(proposal: Proposal) -> list[str]:
    return [
        f"{entry.name.capitalize()} {record_id} is not in the records."
        for field, entry in records.ID_FIELDS.items()
        if (record_id := getattr(proposal.fields, field, None)) is not None
        and not records.known(proposal.department, entry.collection, record_id)
    ]


def _field_report_problems(proposal: Proposal, message: str, today: date) -> list[str]:
    fields = proposal.fields

    if not isinstance(fields, FieldReport):
        return []

    unidentified = [
        f"The report does not identify the {entry.name}."
        for field, entry in records.report_fields().items()
        if getattr(fields, field) is None
    ]
    readings = [
        f"Reading {figure(reading.value)} is not in the report as quoted."
        for reading in fields.readings
        if not _quoted(reading.quote, message, _digits(figure(reading.value)))
    ]
    promises = [
        f"The note lists a commitment ({commitment.words}), and a field report promises nothing."
        for commitment in proposal.commitments
    ]

    return [
        *unidentified,
        *_someone_elses_asset(fields),
        *readings,
        *_visit_date_problems(fields, message, today),
        *promises,
    ]


# The invoice must be the asking customer's own, and named by the customer's words. Without
# such words it may be named only when it is the only invoice the customer has.
def _invoice_problems(proposal: Proposal, message: str, customer_id: str | None) -> list[str]:
    fields = proposal.fields

    if not isinstance(fields, InvoiceDispute):
        return []

    invoice = records.lookup("billing", "invoices", fields.invoice_id)

    if invoice is None:
        return []

    owner, quote = invoice["customer_id"], fields.invoice_quote
    on_record = len(records.list_records("billing", "invoices", owner))
    problems = []

    if customer_id is not None and owner != customer_id:
        problems.append(
            f"Invoice {fields.invoice_id} belongs to customer {owner}, not {customer_id}."
        )

    if quote is None and on_record > 1:
        problems.append(
            f"Invoice {fields.invoice_id} is named without the customer's words that identify "
            f"it, and the customer has {on_record} invoices. Give those words in invoice_quote, "
            "or leave invoice_id empty and ask which invoice is meant."
        )

    if quote is not None and not _appears(quote, message):
        problems.append(
            f"The words “{quote}” that identify invoice {fields.invoice_id} are not in the message."
        )

    return problems


def _quoted(quote: str, message: str, wanted_digits: str) -> bool:
    return _appears(quote, message) and wanted_digits != "" and wanted_digits in _digits(quote)


def _visit_date_problems(fields: FieldReport, message: str, today: date) -> list[str]:
    visit, quote = fields.visit_date, fields.visit_date_quote

    if visit is None or (quote is None and visit == today):
        return []

    if quote is None:
        return [f"Visit date {day(visit)} has no words in the report and is not today."]

    if _appears(quote, message) and _names_date(quote, visit):
        return []

    return [f"Visit date {day(visit)} is not in the report as quoted."]


# The meter or cable must be the customer's own, not one that only matches by number.
def _someone_elses_asset(fields: FieldReport) -> list[str]:
    asset = records.lookup("field_operations", "assets", fields.asset_id)
    customer_known = records.known("field_operations", "customers", fields.customer_id)

    if asset is None or not customer_known or asset["customer_id"] == fields.customer_id:
        return []

    owner = asset["customer_id"]

    return [
        f"Meter or cable {fields.asset_id} belongs to customer {owner}, not {fields.customer_id}."
    ]


def _commitment_problems(proposal: Proposal, message: str) -> list[str]:
    return [
        problem
        for commitment in proposal.commitments
        for problem in _commitment_problem(commitment, proposal, message)
    ]


def _commitment_problem(commitment: Commitment, proposal: Proposal, message: str) -> list[str]:
    words = commitment.words
    in_draft = (
        []
        if _appears(words, proposal.draft)
        else [f"“{words}” is listed as a commitment but is not in the draft."]
    )

    return [*in_draft, *_sourced(commitment, message, proposal.department)]


def _sourced(commitment: Commitment, message: str, department: str) -> list[str]:
    words, source = commitment.words, commitment.source

    if commitment.type == "legal":
        return []

    if source == "message":
        return [] if _appears(words, message) else [f"“{words}” is not in the message."]

    # A usage record has its customer's ID, so one ID can name two records.
    named = [
        (collection, record)
        for collection in records.collections(department)
        for record in records.list_records(department, collection, None)
        if record["id"] == source
    ]

    if not named:
        return [f"Record {source} is not in the records."]

    text = _normalized(words)
    found = any(
        _mentions(text, rendering)
        for collection, record in named
        for field, value in _facts(collection, record)
        for rendering in _renderings(field, value)
    )

    return [] if found else [f"“{words}” is not in record {source}."]


# A record's facts as its tool row shows them. An invoice row also shows the price in the
# customer's tariff record and what the meter recorded that month, so a draft may give the
# invoice as the source of either.
def _facts(collection: str, record: dict) -> list[tuple[str, object]]:
    if collection != "invoices":
        return list(record.items())

    shown = tool_text.invoice_facts(record)

    return [
        *record.items(),
        ("price_per_kwh_eur", shown["tariff"]["price_per_kwh_eur"]),
        ("metered_kwh", shown["metered_kwh"]),
    ]


# The ways a record's value may be written in a draft. A usage record's values are kWh by
# period, such as {"2026-10": 268}.
def _renderings(field: str, value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            rendering
            for period, kwh in value.items()
            for rendering in (*_period_renderings(period), *_renderings(period, kwh))
        ]

    if field == PERIOD_FIELD:
        return _period_renderings(value)

    if isinstance(value, bool):
        return []

    if isinstance(value, int):
        plain = str(value)

        return _unique([plain, *(grouped(plain, separator) for separator in (",", ".", " "))])

    if isinstance(value, float):
        two_decimals, shortest = decimals(value, 2), figure(value)

        return _unique(
            [two_decimals, two_decimals.replace(".", ","), shortest, shortest.replace(".", ",")]
        )

    if isinstance(value, str):
        written = _date(value)

        return [_normalized(value)] if written is None else _date_renderings(written)

    return []


# A period such as "2026-09" as a draft may write it: "September 2026", "sept 2026",
# "09-2026". A month without its year is not enough: it fits every year.
def _period_renderings(period: str) -> list[str]:
    year, month = period.split("-")
    english, dutch = MONTH_NAMES[int(month) - 1]
    numeric = [
        period,
        *(number + separator + year for number in (month, str(int(month))) for separator in "-/"),
    ]
    with_year = [f"{name} {year}" for name in (*english, *dutch)]

    return _unique([*numeric, *with_year])


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _names_date(quote: str, written: date) -> bool:
    text = _normalized(quote)

    return any(_mentions(text, rendering) for rendering in _date_renderings(written))


def _date_renderings(written: date) -> list[str]:
    days = _unique([str(written.day), f"{written.day:02}"])
    months = _unique([str(written.month), f"{written.month:02}"])
    english, dutch = MONTH_NAMES[written.month - 1]
    numeric = [
        day_text + separator + month_text
        for day_text in days
        for month_text in months
        for separator in ("-", "/", ".")
    ]
    named = [
        rendering
        for name in (*english, *dutch)
        for suffix in ORDINAL_SUFFIXES
        for joiner in (" ", " of ")
        for rendering in (f"{written.day}{suffix}{joiner}{name}", f"{name} {written.day}{suffix}")
    ]

    return [written.isoformat(), *numeric, *named]


def _appears(phrase: str | None, text: str) -> bool:
    return bool(phrase) and _normalized(phrase) in _normalized(text)


# Whether `text` holds `rendering` with no digit just before or after it, so "1 nov" is not
# found inside "11 nov".
def _mentions(text: str, rendering: str) -> bool:
    start = text.find(rendering) if rendering else -1

    while start != -1:
        end = start + len(rendering)

        if not _digit_at(text, start - 1) and not _digit_at(text, end):
            return True

        start = text.find(rendering, start + 1)

    return False


def _digit_at(text: str, position: int) -> bool:
    return 0 <= position < len(text) and text[position] in records.DIGITS


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _digits(text: str) -> str:
    return "".join(character for character in text if character in records.DIGITS)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _judge_prompt(proposal: Proposal, message: str, today: date) -> str:
    return (
        f"Today is {today}.\n"
        "\n"
        f"{prompts.evidence(message)}\n"
        "\n"
        "<proposal>\n"
        f"{proposal_json(proposal.model_dump(mode='json'))}\n"
        "</proposal>\n"
    )
