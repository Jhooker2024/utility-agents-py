"""Picks one option from a list of `(value, label)`. In a terminal the arrow keys move the
highlight, typing an option's number jumps to it, and Enter picks it. Anywhere else, such as
piped input or a test, it reads the option's number from a line.
"""

import os
import sys
import termios
import tty

from utility_agents.presenter import paint, terminal
from utility_agents.records import DIGITS

UP = "\x1b[A"
DOWN = "\x1b[B"
ENTER = ("\r", "\n")
INTERRUPT = "\x03"
REVERSE = "\x1b[7m"
RESET = "\x1b[0m"
LABEL_WIDTH = 70

Options = list[tuple[object, str]]


def pick(question: str, options: Options) -> object:
    print("\n" + paint(question, "yellow"))

    if terminal():
        return _pick_with_keys(options)

    return _pick_by_number(options)


def _pick_by_number(options: Options) -> object:
    for index, (_value, label) in enumerate(options):
        print(_line(label, index, selected=False))

    while True:
        typed = _read_line("> ").strip()

        if typed.isascii() and typed.isdecimal() and 1 <= int(typed) <= len(options):
            return options[int(typed) - 1][0]

        print("Type a number from the list.")


def _read_line(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise SystemExit(0) from None


def _pick_with_keys(options: Options) -> object:
    keyboard = sys.stdin.fileno()
    cooked = termios.tcgetattr(keyboard)
    tty.setraw(keyboard)

    try:
        _draw(options, 0)
        index = _choose(options, keyboard)
    finally:
        termios.tcsetattr(keyboard, termios.TCSADRAIN, cooked)

    return options[index][0]


def _choose(options: Options, keyboard: int) -> int:
    index, typed = 0, ""

    while True:
        key = _read_key(keyboard)

        if key in ENTER:
            return index

        if key == INTERRUPT:
            raise SystemExit(0)

        if key == UP:
            index, typed = max(index - 1, 0), ""
        elif key == DOWN:
            index, typed = min(index + 1, len(options) - 1), ""
        elif key in DIGITS:
            typed = next(
                (number for number in (typed + key, key) if 1 <= int(number) <= len(options)), ""
            )
            index = int(typed) - 1 if typed else index
        else:
            continue

        _redraw(options, index)


def _read_key(keyboard: int) -> str:
    key = os.read(keyboard, 1).decode(errors="ignore")

    if key == "\x1b":
        key += os.read(keyboard, 2).decode(errors="ignore")

    return key


def _draw(options: Options, selected: int) -> None:
    lines = [
        _line(label, index, index == selected) for index, (_value, label) in enumerate(options)
    ]
    sys.stdout.write("\r\n".join(lines) + "\r\n")
    sys.stdout.flush()


def _redraw(options: Options, selected: int) -> None:
    sys.stdout.write(f"\x1b[{len(options)}A\x1b[J")
    _draw(options, selected)


# A label is cut to one line: the redraw moves the cursor up one line per option.
def _line(label: str, index: int, selected: bool) -> str:
    if selected:
        return f"{REVERSE}> {index + 1}  {_short(label)}{RESET}"

    return f"  {index + 1}  {_short(label)}"


def _short(label: str) -> str:
    if len(label.encode()) <= LABEL_WIDTH:
        return label

    return label[: LABEL_WIDTH - 3] + "..."
