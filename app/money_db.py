from decimal import Decimal

from dukedining.money import CENT


def to_cents(d: Decimal | None) -> int | None:
    return None if d is None else int((d / CENT).to_integral_value())


def from_cents(c: int | None) -> Decimal | None:
    return None if c is None else (Decimal(c) * CENT).quantize(CENT)


def fmt(c: int | None) -> str:
    if c is None:
        return "—"
    sign = "-" if c < 0 else ""
    return f"{sign}${abs(c) / 100:,.2f}"
