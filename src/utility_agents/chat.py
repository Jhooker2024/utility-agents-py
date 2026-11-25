"""The interactive front end: run `utility-agents` with no arguments.

Three kinds of request, each typed in your own words: an HR question, a customer's message
about a bill, and a field report. HR and billing show what people can ask about first. A field
report that does not say which customer or meter it is about asks for them at the end and runs
again with them. Every request goes through `request_path.handle`, the same path as the command
line, and shows the outcome, the draft or CRM update and why. A "What next?" list then shows
the checks and steps, or approves, edits or rejects a draft, recorded as a staff review. The
demo and the evals run from the same menu.
"""

from utility_agents import decisions, demo, evaluation, proposal, records, request_path, trace
from utility_agents.config import settings
from utility_agents.picker import pick, read_line
from utility_agents.presenter import clear, details, paint, summary, terminal
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
MISSING_QUESTIONS = {
    "customer": "Which customer was it? A name and street: ",
    "meter": "Which meter was it? The meter number: ",
}


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
    _submit("hr_portal", _required("What does the employee ask? "), None)


def _billing() -> None:
    clear()
    print(_topics("BILLING", "A customer can write about:", BILLING_TOPICS))
    email = _answer("The customer's email address (press Enter if you don't know it): ")
    customer = records.customer_by_email(email)

    if customer is None:
        print("From someone not on record: the agent looks for a name or address in the message.")
    else:
        print(f"From {customer['name']} ({customer['id']}), known by their email address.")

    _submit(
        "billing_portal", _required("What does the customer write? "), customer and customer["id"]
    )


def _field_report() -> None:
    clear()
    print(paint("FIELD REPORT", "bright"))
    print(
        "Write what happened on the visit: who it was for (a name and street, or a meter\n"
        "number), what you found and did, any readings, and anything still to do.\n"
    )
    _submit("field_app", _required("Report: "), None)


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


def _submit(channel: str, message: str, customer_id: str | None) -> None:
    clear()
    print("\n" + paint(message, "yellow") + "\n\nWorking on it...\n")

    decision = request_path.handle(request_path.new_request(channel, message, customer_id))
    print(summary(decision))
    names = _missing(decision)

    if names:
        _complete(names, decision, message)
    else:
        _next(decision, message)


# A field report that does not say which customer or meter it is about asks for them, then
# runs again with them. Enter leaves them for a person.
def _complete(names: list[str], decision: dict, message: str) -> None:
    print(paint(f"The report does not say which {' or '.join(names)} it was.", "yellow"))
    asked = [(name, _answer(MISSING_QUESTIONS[name])) for name in names]
    added = [f"{name} {given}" for name, given in asked if given != ""]

    if added:
        _submit("field_app", message + "\nAdded by the technician: " + "; ".join(added), None)
    else:
        _next(decision, message)


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


def _required(prompt: str) -> str:
    while True:
        text = _answer(prompt)

        if text != "":
            return text


def _answer(prompt: str) -> str:
    return read_line(paint(prompt, "yellow")).strip()
