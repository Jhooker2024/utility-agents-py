"""Command line entry point.

    utility-agents                              (no arguments: the interactive menu)
    utility-agents demo [--detail]              (five real requests, step by step)
    utility-agents run <request_id>
    utility-agents submit <field_app|email|web_chat|billing_portal|hr_portal> "<text>"
    utility-agents review <request_id> <sent_unedited|edited|rejected> --kind <kind>
                          [--field name=value ...]
    utility-agents eval [--playbook <playbook>] [--runs <1-10>] [--model <model_id>]

Variables in `.env` in the current directory, such as `ANTHROPIC_API_KEY=...`, are loaded first,
so the key never has to be typed into a shell.

`run` and `submit` print the decision as JSON; a request decided before prints its stored
decision. `review` records what a person did with a decision. `eval` runs a playbook's labelled
cases, or every playbook's when none is named, each run on its own under the log directory,
prints how many passed and exits 1 when a playbook fails (`evaluation`).
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from utility_agents import chat, decisions, demo, evaluation, proposal, request_path
from utility_agents.config import settings

USAGE = __doc__
# Each eval run is one paid model call per case, so the runs per case are capped.
MAX_RUNS = 10
ENV_FILE = ".env"

Outcome = tuple[str, str]


def main() -> None:
    load_env(Path(ENV_FILE))
    arguments = sys.argv[1:]

    if arguments == []:
        chat.start()
    elif arguments in (["demo"], ["demo", "--detail"]):
        demo.run(detail="--detail" in arguments)
    else:
        status, output = run(arguments)
        print(output, file=sys.stderr if status == "error" else sys.stdout)
        sys.exit(0 if status == "ok" else 1)


def run(arguments: list[str]) -> Outcome:
    """Runs a command: `ok`, `failed` or `error`, with the output or the message to print."""
    match arguments:
        case ["run", request_id]:
            return _decide(request_id)
        case ["submit", channel, message]:
            return _printed(request_path.handle(request_path.new_request(channel, message, None)))
        case ["review", request_id, action, *rest]:
            return _review(request_id, action, rest)
        case ["eval", *rest]:
            return _eval(rest)
        case _:
            return "error", USAGE


def load_env(path: Path) -> None:
    """Sets every `NAME=value` line of the file as an environment variable. A line that
    starts with `#` or has no value is skipped."""
    if not path.exists():
        return

    for line in path.read_text().split("\n"):
        name, separator, value = line.partition("=")

        if separator and not name.startswith("#") and value.strip() != "":
            os.environ[name.strip()] = value.strip()


def _decide(request_id: str) -> Outcome:
    try:
        request = request_path.request(request_id)
    except request_path.UnknownRequest as unknown:
        return "error", str(unknown)

    return _printed(request_path.handle(request))


def _review(request_id: str, action: str, arguments: list[str]) -> Outcome:
    options = _parse(arguments, kind=str, field=[])

    if options is None or action not in decisions.ACTIONS or options.kind not in proposal.KINDS:
        return "error", USAGE

    pairs = [pair.partition("=") for pair in options.field]

    if not all(separator for _name, separator, _value in pairs):
        return "error", USAGE

    review = {
        "action": action,
        "kind": options.kind,
        "fields": {name: value for name, _separator, value in pairs},
        "date": datetime.now(UTC).date(),
    }

    try:
        return _printed(decisions.review(settings["log_directory"], request_id, review))
    except decisions.NoDecision as missing:
        return "error", str(missing)


def _eval(arguments: list[str]) -> Outcome:
    options = _parse(arguments, playbook=str, model=str, runs=int)

    if options is None:
        return "error", USAGE

    playbooks = list(proposal.PLAYBOOKS) if options.playbook is None else [options.playbook]
    runs = 1 if options.runs is None else options.runs

    if not set(playbooks) <= set(proposal.PLAYBOOKS) or not 1 <= runs <= MAX_RUNS:
        return "error", USAGE

    evaluated = [evaluation.run(playbook, runs=runs, model=options.model) for playbook in playbooks]
    report = "\n\n".join(map(evaluation.report, evaluated))

    return ("ok" if all(map(evaluation.passed, evaluated)) else "failed"), report


# The options a command takes, or None when an argument is not one of them. An option given
# a list may be repeated.
def _parse(arguments: list[str], **switches: type | list) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False, allow_abbrev=False)

    for name, kind in switches.items():
        if kind == []:
            parser.add_argument(f"--{name}", action="append", default=[])
        else:
            parser.add_argument(f"--{name}", type=kind)

    try:
        options, unknown = parser.parse_known_args(arguments)
    except argparse.ArgumentError:
        return None

    return None if unknown else options


def _printed(entry: dict) -> Outcome:
    return "ok", json.dumps(entry, indent=2, ensure_ascii=False)
