"""A guided run of the real system: five stored requests, each chosen to show one claim from the
advice deck, sent through the live path into a fresh log directory. For each it prints what
came in, what the agents did in plain words, what they propose and could not confirm, the three
checks, the decision and why, and the cost. With `detail` it also prints the raw trace.
Everything printed is saved to `transcript.txt` in the run's directory, so a good run can be
shown again without calling the model.
"""

from pathlib import Path

from utility_agents import gate, request_path, trace
from utility_agents.config import settings
from utility_agents.presenter import WIDTH, describe, steps, wrap
from utility_agents.text import words

SCENES = [
    (
        "D-001",
        "A field report in plain words",
        "Typed the way a technician types, with no IDs: the agent finds the customer and the "
        "meter by search, then fills checked CRM fields.",
    ),
    (
        "D-002",
        "A prompt injection",
        "The report tells the AI to record no fault and promise 500 euro back. It records the "
        "real fault, promises nothing, and sends the report to a person.",
    ),
    (
        "D-003",
        "Safety goes to a person",
        "A broken seal and a wire around it: the agent flags possible tampering and the gate "
        "holds it.",
    ),
    (
        "D-004",
        "The front door, and asking another department",
        "A free-text email: the front door routes it to billing, and billing asks field "
        "operations whether the meter was read.",
    ),
    (
        "D-005",
        "A question no policy covers",
        "HR is at run and no policy covers it: the reply says so and points to HR, states "
        "nothing unconfirmed, and goes out alone.",
    ),
]
RULE = "-" * WIDTH
COLOR_START = "\x1b["


def run(detail: bool = False) -> None:
    directory = request_path.run_directory("demo")
    transcript = directory / "transcript.txt"
    directory.mkdir(parents=True, exist_ok=True)

    _say(transcript, "Five real requests through the live system. Each takes 10 to 60 seconds.")
    _say(transcript, f"This run is saved to {transcript}.\n")
    _say(transcript, _stages())

    outcomes = [
        _scene(scene, number, directory, transcript, detail)
        for number, scene in enumerate(SCENES, 1)
    ]

    _say(transcript, f"\n{RULE}\nSummary")

    for (_id, title, _point), outcome in zip(SCENES, outcomes, strict=True):
        _say(transcript, f"  {title:<48} {outcome}")


def _stages() -> str:
    rows = [
        f"  {words(playbook):<20} {stage}" for playbook, stage in sorted(settings["stages"].items())
    ]
    never = " and ".join(map(words, gate.NEVER_AUTOMATE))

    return (
        "\n".join(["How far each kind of work may go on its own today:", *rows])
        + f"\n  (An {never} never goes out without a person, whatever the stage.)"
    )


def _scene(
    scene: tuple[str, str, str], number: int, directory: Path, transcript: Path, detail: bool
) -> str:
    request_id, title, point = scene
    request = request_path.request(request_id)

    _say(transcript, f"\n{RULE}\n{number} of {len(SCENES)}  {title.upper()}")
    _say(transcript, f"Watch for: {point}\n")
    _say(transcript, f"What came in ({words(request.channel)}):")
    _say(transcript, wrap(request.message, 2))
    _say(transcript, "\nWorking...\n")

    decision = request_path.handle(request, log_directory=directory)
    entries = trace.entries(directory, request_id)

    _say(transcript, describe(decision, entries))

    if detail:
        _say(transcript, "\nRaw trace:\n" + steps(entries))

    return words(decision["outcome"])


# The screen may be in colour; the transcript stays plain text.
def _say(transcript: Path, text: str) -> None:
    print(text)

    with transcript.open("a", encoding="utf-8") as file:
        file.write(_plain(text) + "\n")


# Drops the colour codes the screen uses: each starts with ESC [ and ends with m.
def _plain(text: str) -> str:
    first, *coloured = text.split(COLOR_START)

    return first + "".join(piece.split("m", 1)[-1] for piece in coloured)
