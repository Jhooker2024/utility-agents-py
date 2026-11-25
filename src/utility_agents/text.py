"""How values are written for people: dates, months, names, amounts and counts."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def day(value: date) -> str:
    """A date as people write it, such as `24 Nov 2026`."""
    return f"{value.day} {MONTHS[value.month - 1][:3]} {value.year}"


def month(period: str) -> str:
    """A period such as `2026-10` as `October 2026`."""
    first = date.fromisoformat(period + "-01")

    return f"{MONTHS[first.month - 1]} {first.year}"


def words(name: object) -> str:
    """A name such as `field_report` as words."""
    return str(name).replace("_", " ")


def decimals(number: float, places: int) -> str:
    """A number with exactly `places` decimals: decimals(5, 2) is "5.00"."""
    return f"{float(number):.{places}f}"


def rounded(number: float, places: int = 0) -> Decimal:
    """A number rounded to `places` decimals, a half away from zero: rounded(12.5) is 13."""
    return Decimal(number).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def figure(number: float) -> str:
    """A number as short as it can be written: 9876.0 is "9876" and 4.8 is "4.8"."""
    if number == int(number):
        return str(int(number))

    return repr(number)


def grouped(digits: str, separator: str) -> str:
    """Digits in groups of three from the right: grouped("14502", ".") is "14.502"."""
    groups = [digits[max(end - 3, 0) : end] for end in range(len(digits), 0, -3)]

    return separator.join(reversed(groups))
