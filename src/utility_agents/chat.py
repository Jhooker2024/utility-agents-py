"""The interactive front end: run `utility-agents` with no arguments.

Three kinds of request, each typed in your own words: an HR question, a customer's message
about a bill, and a field report. HR and billing show what people can ask about first. Enter on
an empty line goes back to the menu. A field report that does not say which customer or meter
it is about asks for them once: it offers the customers the agent found that the report could
mean and that customer's meters and cables, and "I don't know" always leaves it for a person.
It then runs once more with the answers and asks nothing further. Every request goes through
`request_path.handle`, the same path as the command line, and shows the outcome, the draft or
CRM update and why. A "What next?" list then shows the checks and steps, or approves, edits or
rejects a draft, recorded as a staff review. The demo and the evals run from the same menu.
"""

from utility_agents import decisions, demo, evaluation, proposal, records, request_path, trace
from utility_agents.config import settings
from utility_agents.picker import pick, read_line
from utility_agents.presenter import clear, details, field_text, paint, summary, terminal
from utility_agents.text import words

MENU = [
    ("hr", "HR: a question from an employee"),
    ("billing", "Billing: a message from a customer about a bill"),
    ("field_report", "Field report: a technician's visit"),
    ("demo", "Run everything: the demo with five requests"),
    ("eval", "Run the evals (benchmarks)"),
    ("quit", "Quit"),
]
BILLING_TOPICS = [
    "a bill that is higher than expected",
    "a meter reading that looks wrong or was estimated",
    "an invoice that is missing",
    "an amount they do not recognise",
    "how a bill compares with their earlier bills",
]
EVALS = [
    ("policy_question", "HR"),
    ("invoice_dispute", "Billing"),
    ("field_report", "Field reports"),
]
GO_BACK = " (or press Enter to go back) "
ASK_CUSTOMER = "Which customer was it? A name and street (press Enter if you don't know): "
ASK_METER = "Which meter was it? The meter number (press Enter if you don't know): "
SOMEONE_ELSE = "Someone else: type a name and street"
NOT_KNOWN = "I don't know: leave it for a person"
OTHER = "other"


def start() -> None:
    """Every screen starts at the top of the terminal, so nothing scrolls out of view."""
    while True:
        clear()
        print("Utility agents. Use the arrow keys and Enter, or type a number.")
        choice = pick("What do you want to do?", MENU)

        match choice:
            case "hr":
                _hr()
            case "billing":
                _billing()
            case "field_report":
                _field_report()
            case "demo":
                _demo()
            case "eval":
                _eval()
            case "quit":
                return


def _hr() -> None:
    policies = [policy["title"] for policy in records.list_records("hr", "policies", None)]

    clear()
    print(_topics("HR", "An employee can ask about these policies:", policies))
    _submit("hr_portal", _answer("What does the employee ask?" + GO_BACK), None)


def _billing() -> None:
    clear()
    print(_topics("BILLING", "A customer can write about:", BILLING_TOPICS))
    email = _answer("The customer's email address (press Enter if you don't know it): ")
    customer = records.customer_by_email(email)

    if customer is None:
        print("From someone not on record: the agent looks for a name or address in the message.")
    else:
        print(f"From {customer['name']} ({customer['id']}), known by their email address.")

    message = _answer("What does the customer write?" + GO_BACK)
    _submit("billing_portal", message, customer and customer["id"])


def _field_report() -> None:
    clear()
    print(paint("FIELD REPORT", "bright"))
    print(
        "Write what happened on the visit: who it was for (a name and street, or a meter\n"
        "number), what you found and did, any readings, and anything still to do.\n"
    )
    _submit("field_app", _answer("Report" + GO_BACK), None)


def _demo() -> None:
    demo.run()
    _pause()


def _eval() -> None:
    one = [([entry], entry[1]) for entry in EVALS]
    chosen = pick("Which evals?", [*one, (EVALS, "All three")])

    for playbook, name in chosen:
        print(f"Running every labelled case for {name}. This takes a few minutes.")
        print(evaluation.report(evaluation.run(playbook)))

    _pause()


def _topics(heading: str, intro: str, topics: list[str]) -> str:
    return "\n".join([paint(heading, "bright"), intro, *("  - " + topic for topic in topics), ""])


# A message of nothing goes back to the menu. A field report with something missing is asked
# about once and runs once more with the answers: the second result goes to a person as it
# is, so a report never loops.
def _submit(channel: str, message: str, customer_id: str | None) -> None:
    if message == "":
        return

    decision = _decided(channel, message, customer_id)
    added = _added(decision)

    if added:
        message = f"{message}\nAdded by the technician: {'; '.join(added)}"
        decision = _decided("field_app", message, None)

    _next(decision, message)


def _decided(channel: str, message: str, customer_id: str | None) -> dict:
    clear()
    print("\n" + paint(message, "yellow") + "\n\nWorking on it...\n")

    decision = request_path.handle(request_path.new_request(channel, message, customer_id))
    print(summary(decision))

    return decision


def _added(decision: dict) -> list[str]:
    """What the technician adds to a field report that does not say which customer or meter
    it was; nothing when they do not know either."""
    missing = _missing(decision)

    if not missing:
        return []

    print(paint(f"The report does not say which {' or '.join(missing)} it was.", "yellow"))
    fields = decision["proposal"]["fields"]
    customer_id, customer = fields["customer_id"], []

    if "customer" in missing:
        customer_id, customer = _customer_asked(fields["possible_customer_ids"])

    meter = _meter_asked(customer_id, "customer" in missing) if "meter" in missing else []

    return [*customer, *meter]


# The customers the agent found that the report could mean are offered by name. Returns the
# ID picked, if one was, and what to add to the report.
def _customer_asked(possible: list[str]) -> tuple[str | None, list[str]]:
    found = [
        customer_id
        for customer_id in possible
        if records.known("field_operations", "customers", customer_id)
    ]
    offered = [(customer_id, field_text("customer_id", customer_id)) for customer_id in found]
    choice = OTHER

    if offered:
        choice = pick(
            "Which customer was it?", [*offered, (OTHER, SOMEONE_ELSE), (None, NOT_KNOWN)]
        )

    if choice is None:
        return None, []

    if choice == OTHER:
        typed = _answer(ASK_CUSTOMER)

        return None, [f"customer {typed}"] if typed else []

    return choice, [f"customer {field_text('customer_id', choice)}"]


# A customer on record has their meters and cables offered. One just picked who has a single
# asset is not asked: the agent takes that asset.
def _meter_asked(customer_id: str | None, just_picked: bool) -> list[str]:
    if not records.known("field_operations", "customers", customer_id):
        typed = _answer(ASK_METER)

        return [f"meter {typed}"] if typed else []

    assets = records.list_records("field_operations", "assets", customer_id)

    if just_picked and len(assets) == 1:
        return []

    offered = [(asset, field_text("asset_id", asset["id"])) for asset in assets]
    asset = pick("Which meter or cable was it?", [*offered, (None, NOT_KNOWN)])

    return [] if asset is None else [f"{words(asset['type'])} {asset['id']}"]


# What can be done with this result: offered after every result until "Back to the menu".
def _next(decision: dict, message: str) -> None:
    while True:
        options = [
            ("details", "Show the checks and the agents' steps"),
            *_reviews(decision),
            ("back", "Back to the menu"),
        ]
        choice = pick("What next?", options)

        if choice == "back":
            return

        if choice == "details":
            clear()
            print("\n" + paint(message, "yellow") + "\n")
            print(
                details(decision, trace.entries(settings["log_directory"], decision["request_id"]))
            )
        else:
            _record_review(choice, decision)


def _missing(decision: dict) -> list[str]:
    if decision.get("playbook") != "field_report" or decision.get("proposal") is None:
        return []

    fields = decision["proposal"]["fields"]

    return [
        entry.short_name
        for field, entry in records.report_fields().items()
        if not records.known("field_operations", entry.collection, fields.get(field))
    ]


# What a person may do with the result: undo work that went ahead alone; never approve a
# draft as it is when a check failed.
def _reviews(decision: dict) -> list[tuple[str, str]]:
    if decision.get("proposal") is None:
        return []

    if decision["outcome"] == "automatic":
        return [("rejected", "Reject it: it should not have gone ahead")]

    passed = all(result == "pass" for result in decision["checks"].values())
    approval = [("sent_unedited", "Approve the draft as it is")] if passed else []

    return [*approval, ("edited", "Approve it after editing"), ("rejected", "Reject it")]


def _record_review(action: str, decision: dict) -> None:
    if action == "rejected":
        kinds = [(kind, words(kind)) for kind in proposal.KINDS]
        kind = pick("What should it have been instead?", kinds)
    else:
        kind = decision["proposal"]["kind"]

    review = {"action": action, "kind": kind, "fields": {}, "date": request_path.utc_today()}

    try:
        decisions.review(settings["log_directory"], decision["request_id"], review)
        print("Recorded as a staff review.")
    except decisions.NoDecision as missing:
        print(missing)


# A screen with nothing to pick from waits for Enter, so the next clear does not wipe it.
def _pause() -> None:
    if terminal():
        _answer("\nPress Enter to go back to the menu. ")


def _answer(prompt: str) -> str:
    return read_line(paint(prompt, "yellow")).strip()
