"""Token usage and cost per request. Every API response adds its usage to the count of the
request being worked; `request_path.handle` starts a count before a request and takes it after,
so the decision records what that request cost. Requests worked at the same time, as in the
eval, each keep their own count. The agent's graph runs its steps in a copy of the caller's
context, so a count is one list that every copy shares. Prices are per million tokens, in the
`prices` setting; a model without a price has no cost.
"""

from contextvars import ContextVar

from utility_agents.config import settings
from utility_agents.text import decimals

PRICES = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_creation_input_tokens": "cache_write",
    "cache_read_input_tokens": "cache_read",
}

_calls: ContextVar[list[tuple[str, dict[str, int]]]] = ContextVar("usage")


def start() -> None:
    _calls.set([])


def add(model: str, usage: dict) -> None:
    """Adds one API response's usage for `model`."""
    counts = {field: usage.get(field) or 0 for field in PRICES}
    calls = _calls.get(None)

    if calls is None:
        calls = []
        _calls.set(calls)

    calls.append((model, counts))


def take() -> dict:
    """The tokens counted since `start`, summed, and their cost in US dollars."""
    calls = _calls.get([])
    _calls.set([])
    tokens = {field: sum(counts[field] for _model, counts in calls) for field in PRICES}

    return {**tokens, "cost_usd": _cost(calls)}


def dollars(cost: float) -> str:
    """A cost in US dollars to four decimals, such as `$0.0070`."""
    return "$" + decimals(cost, 4)


def _cost(calls: list[tuple[str, dict[str, int]]]) -> float | None:
    costs = [_call_cost(settings["prices"].get(model), counts) for model, counts in calls]

    if None in costs:
        return None

    return float(sum(costs))


def _call_cost(price: dict | None, counts: dict[str, int]) -> float | None:
    if price is None:
        return None

    return sum(tokens * price[PRICES[field]] / 1_000_000 for field, tokens in counts.items())
