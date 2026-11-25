"""The tools a department agent can call. Every department gets the read tools over its own
records. A department filing a proposal also gets `ask_department` and its playbook's
`file_proposal`; a consulted department gets the read tools only.

Every definition is a strict schema, so the API checks the arguments before a tool runs. A
`ToolError` goes back to the model, so its text says what to send instead.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from utility_agents import department, proposal, records, tool_text, verifier
from utility_agents.schema import strict_object


class ToolError(Exception):
    """A tool could not do what the model asked; the text goes back to the model."""


@dataclass(frozen=True)
class Context:
    """What a department works under: the day, the model of every role, and for one request
    its ID, playbook, department and message. `mode` is `propose` for the department that
    files the proposal and `consult` for one that only answers a question."""

    today: date
    models: dict[str, str]
    log_directory: str = ""
    request_id: str = ""
    playbook: str = ""
    department: str = ""
    message: str = ""
    mode: str = "propose"
    consults_left: int = 0


class Tool(NamedTuple):
    name: str
    description: str
    input_schema: Callable[[Context], dict]
    call: Callable[[dict, Context], object]


def definitions(context: Context) -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema(context),
            "strict": True,
        }
        for tool in _offered(context)
    ]


def call(name: str, arguments: dict, context: Context) -> object:
    """Runs the tool the model named: the text it reads back, or for `file_proposal` the
    proposal."""
    tool = next((tool for tool in _offered(context) if tool.name == name), None)

    if tool is None:
        raise ToolError(f"Unknown tool {name}.")

    return tool.call(arguments, context)


def _find_customer(arguments: dict, context: Context) -> str:
    query = arguments["query"]
    matches = records.search_customers(context.department, query)

    if not matches:
        return f"No customer matches every word of: {query}"

    return tool_text.customers(matches)


def _get_record(arguments: dict, context: Context) -> str:
    collection = _in_scope(arguments["collection"], context)
    record = records.lookup(context.department, collection, arguments["id"])

    if record is None:
        return "No record has that ID."

    return tool_text.listed(collection, [record], context.today)


def _list_records(arguments: dict, context: Context) -> str:
    collection = _in_scope(arguments["collection"], context)
    found = records.list_records(context.department, collection, arguments.get("customer_id"))

    return tool_text.listed(collection, found, context.today)


def _ask_department(arguments: dict, context: Context) -> str:
    if context.consults_left == 0:
        raise ToolError("No consults left for this request. File your proposal with what you have.")

    asked = arguments["department"]

    if asked not in _others(context):
        raise ToolError(f"{asked} is not a department you can ask: {', '.join(_others(context))}.")

    return department.consult(asked, arguments["question"], context)


# The fact check runs here, while the agent can still fix what it finds, as a tool error. A
# proposal for a person (needs_attention) is not sent back: a person handles it and sees the
# check's result anyway.
def _file_proposal(arguments: dict, context: Context) -> proposal.Proposal:
    try:
        filed = proposal.new(arguments, context.request_id, context.department, context.playbook)
    except proposal.Invalid as invalid:
        raise ToolError(str(invalid)) from invalid

    if filed.kind == "needs_attention":
        return filed

    problems = verifier.grounded(filed, context.message, context.today)

    if problems is not None:
        raise ToolError(
            "The proposal does not match the message or the records: "
            + problems
            + " Fix these and file again. If the message does not give what is missing, file "
            "kind needs_attention and say what is missing."
        )

    return filed


def _collection_property(context: Context) -> dict:
    return {"type": "string", "enum": list(records.collections(context.department))}


def _in_scope(collection: str, context: Context) -> str:
    if collection not in records.collections(context.department):
        raise ToolError(f"{collection} is outside your department's records.")

    return collection


def _others(context: Context) -> list[str]:
    return [name for name in proposal.DEPARTMENTS if name != context.department]


FIND_CUSTOMER = Tool(
    "find_customer",
    "Find customers by what a message or report says about them: a name, a street and "
    "number, a town, an email address, or a meter or cable ID. Every word must appear; "
    "case, accents and the spaces inside a name do not matter. "
    "Returns each matching customer with their meters and cables. Use the fewest words "
    "that identify them, such as a surname and a street.",
    lambda _context: strict_object({"query": {"type": "string"}}, ["query"]),
    _find_customer,
)
GET_RECORD = Tool(
    "get_record",
    "Read one record of your department by its ID: a customer (C-), asset (A-), "
    "invoice (INV-) or policy (P-). Usage records use the customer ID.",
    lambda context: strict_object(
        {"collection": _collection_property(context), "id": {"type": "string"}},
        ["collection", "id"],
    ),
    _get_record,
)
LIST_RECORDS = Tool(
    "list_records",
    "List the records of one collection of your department, such as every policy. "
    "customer_id keeps only that customer's records; tariffs and policies are always whole.",
    lambda context: strict_object(
        {"collection": _collection_property(context), "customer_id": {"type": "string"}},
        ["collection"],
    ),
    _list_records,
)
ASK_DEPARTMENT = Tool(
    "ask_department",
    "Ask another department one question about records only it can read, such as an "
    "invoice or an asset. It answers from its records in text; it cannot act.",
    lambda context: strict_object(
        {
            "department": {"type": "string", "enum": _others(context)},
            "question": {"type": "string"},
        },
        ["department", "question"],
    ),
    _ask_department,
)
FILE_PROPOSAL = Tool(
    "file_proposal",
    "File your proposal for this request. It goes to the gate and to staff; it is not sent "
    "or written anywhere by itself. Call it once, as your last step.",
    lambda context: proposal.json_schema(context.playbook),
    _file_proposal,
)
READ_TOOLS = (FIND_CUSTOMER, GET_RECORD, LIST_RECORDS)
PROPOSAL_TOOLS = (ASK_DEPARTMENT, FILE_PROPOSAL)


def _offered(context: Context) -> list[Tool]:
    customers = "customers" in records.collections(context.department)
    read_tools = [tool for tool in READ_TOOLS if customers or tool is not FIND_CUSTOMER]

    if context.mode == "consult":
        return read_tools

    return [*read_tools, *PROPOSAL_TOOLS]
