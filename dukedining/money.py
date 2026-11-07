"""Money and Durham County sales-tax arithmetic. Everything is Decimal, never float."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

TAX_RATE = Decimal("0.075")  # Durham County: 4.75% NC + 2.75% local
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(s: str | float | Decimal) -> Decimal:
    """Parse '1,023.00' / '13.81' / Decimal into a cent-quantized Decimal."""
    return Decimal(str(s).replace(",", "").replace("$", "").strip()).quantize(CENT)


def round_half_up(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def tax_on(taxable: Decimal) -> Decimal:
    return round_half_up(taxable * TAX_RATE)


def with_tax(subtotal: Decimal) -> Decimal:
    """What a purchase with this pre-tax subtotal charges (no board swipe)."""
    return subtotal + tax_on(subtotal)


def receipt_tax(subtotal: Decimal, swipe: Decimal = ZERO) -> Decimal:
    """Tax on a receipt: with a board-plan swipe only the amount above the swipe is taxed."""
    return tax_on(max(subtotal - swipe, ZERO))


def pretax_candidates(charged: Decimal) -> list[Decimal]:
    """Every pre-tax subtotal S with with_tax(S) == charged (usually one; can be zero or two)."""
    if charged <= 0:
        return []
    guess = round_half_up(charged / (1 + TAX_RATE))
    out = []
    for cents in range(-3, 4):
        s = guess + CENT * cents
        if s > 0 and with_tax(s) == charged:
            out.append(s)
    return out


def pretax_for(charged: Decimal) -> Decimal:
    """Best pre-tax price for a charge: an exact one if it exists, else charged / 1.075 rounded."""
    exact = pretax_candidates(charged)
    guess = round_half_up(charged / (1 + TAX_RATE))
    if exact:
        return min(exact, key=lambda s: abs(s - guess))
    return guess
