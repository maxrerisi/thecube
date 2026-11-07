"""Match eAccounts purchases to receipts (mobile orders) or catalog candidates (in person)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from .catalog import ITEM, CatalogEntry
from .eaccounts import Purchase
from .money import pretax_candidates
from .receipts import Receipt

MATCH_WINDOW = timedelta(minutes=2)
SWIPE_REMAINDER = Decimal("0.10")

# Match statuses (persisted by the app)
ITEMIZED = "itemized"  # mobile order matched to its receipt
UNIQUE = "unique"  # exactly one catalog combination fits
AMBIGUOUS = "ambiguous"  # several combinations fit; ask the user
USER_CONFIRMED = "user_confirmed"
UNKNOWN = "unknown"  # nothing fits / not itemizable
NOT_FOOD = "not_food"  # deposits, printing, voids
STATUSES = (ITEMIZED, UNIQUE, AMBIGUOUS, USER_CONFIRMED, UNKNOWN, NOT_FOOD)

# Candidate sources, in matching priority order
OWN, SHARED = "own", "shared"
HERE, OTHER_LOCATIONS = "here", "other locations"


@dataclass
class MatchResult:
    status: str
    # void / deposit / print / itemized / swipe_remainder / receipt_missing / in_person / not_itemizable
    detail: str
    receipt: Receipt | None = None
    candidates: list[list[CatalogEntry]] = field(default_factory=list)
    source: str = ""  # own / shared (which catalog the candidates came from)
    scope: str = ""  # here / other locations
    location: str | None = None  # catalog location name used for in-person matching


# --------------------------------------------------------------------------- mobile orders
def find_receipt(p: Purchase, receipts: list[Receipt]) -> Receipt | None:
    """|time| <= 2 min AND amount == the receipt's Student Food tender."""
    for r in receipts:
        paid = r.food_points
        if paid is None:
            continue
        if abs(r.when - p.when) <= MATCH_WINDOW and paid == p.spent:
            return r
    return None


def learn_location_aliases(purchases: list[Purchase], receipts: list[Receipt]) -> dict[str, str]:
    """Map eAccounts terminal codes ('SPR') to receipt location names
    ('Farmstead & Sprout Sandwiches') by pairing mobile orders with receipts."""
    alias: dict[str, str] = {}
    for p in purchases:
        t = p.terminal
        if not t or p.channel != "mobile order":
            continue
        r = find_receipt(p, receipts)
        if r:
            alias.setdefault(t[1], r.location)
    return alias


def location_for(p: Purchase, alias: dict[str, str]) -> str | None:
    """Catalog location name for an in-person purchase: the learned alias, else the eAccounts
    name without its terminal code ('Commons COMReg1' -> 'Commons')."""
    t = p.terminal
    if not t:
        return None
    return alias.get(t[1]) or t[0]


# --------------------------------------------------------------------------- in-person candidates
def candidates(amount: Decimal, entries: list[CatalogEntry], max_items: int = 3) -> list[list[CatalogEntry]]:
    """All multisets of up to max_items catalog lines whose taxed total equals amount.
    Add-ons are only allowed alongside at least one item.

    Ranked by fewest lines, then most often ordered (ties: catalog order). Runs in O(n^2)
    instead of enumerating all O(n^3) combinations, so it scales to a shared catalog."""
    targets = set(pretax_candidates(amount))
    if not targets or not entries:
        return []
    by_price: dict[Decimal, list[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        by_price[e.price].append(i)

    found: list[tuple[int, ...]] = []
    for s in targets:
        found += [(i,) for i in by_price.get(s, [])]
        if max_items >= 2:
            for i, a in enumerate(entries):
                found += [(i, j) for j in by_price.get(s - a.price, []) if j >= i]
        if max_items >= 3:
            for i, a in enumerate(entries):
                for j in range(i, len(entries)):
                    rest = s - a.price - entries[j].price
                    if rest < 0:
                        continue
                    found += [(i, j, k) for k in by_price.get(rest, []) if k >= j]
    found = [c for c in found if any(entries[i].kind == ITEM for i in c)]
    found.sort(key=lambda c: (len(c), -sum(entries[i].times for i in c), c))
    return [[entries[i] for i in c] for c in found]


def describe(combo: list[CatalogEntry]) -> str:
    parts = []
    for e in combo:
        v = f" [{'/'.join(sorted(e.variants))}]" if e.variants and e.kind == ITEM else ""
        parts.append(f"{e.item}{v} ${e.price}")
    return " + ".join(parts)


def in_person_candidates(
    amount: Decimal, location: str | None, pools: list[tuple[str, list[CatalogEntry]]]
) -> tuple[list[list[CatalogEntry]], str, str]:
    """Try each catalog pool (own first, then shared) at this location; if nothing fits,
    fall back to every location (up to 2 lines). Returns (candidates, source, scope)."""
    if location:
        for source, entries in pools:
            here = [e for e in entries if e.location == location]
            if here and (c := candidates(amount, here)):
                return c, source, HERE
    merged: dict[tuple, CatalogEntry] = {}
    origin: dict[tuple, str] = {}
    for source, entries in pools:
        for e in entries:
            if e.key not in merged:
                merged[e.key] = e
                origin[e.key] = source
    c = candidates(amount, list(merged.values()), max_items=2)
    if not c:
        return [], "", ""
    sources = {origin[e.key] for combo in c for e in combo}
    return c, (OWN if sources == {OWN} else SHARED), OTHER_LOCATIONS


# --------------------------------------------------------------------------- classify
def classify(
    p: Purchase,
    receipts: list[Receipt],
    alias: dict[str, str],
    pools: list[tuple[str, list[CatalogEntry]]],
) -> MatchResult:
    ch = p.channel
    if p.spent == 0:
        return MatchResult(NOT_FOOD, "void")
    if ch == "deposit":
        return MatchResult(NOT_FOOD, "deposit")
    if ch == "print":
        return MatchResult(NOT_FOOD, "print")
    if ch == "mobile order":
        r = find_receipt(p, receipts)
        if r:
            return MatchResult(ITEMIZED, "itemized", receipt=r)
        if p.spent in (SWIPE_REMAINDER, -SWIPE_REMAINDER):
            return MatchResult(UNKNOWN, "swipe_remainder")
        return MatchResult(UNKNOWN, "receipt_missing")
    if ch in ("register", "kiosk"):
        loc = location_for(p, alias)
        cands, source, scope = in_person_candidates(p.spent, loc, pools)
        if not cands:
            status = UNKNOWN
        elif len(cands) == 1:
            status = UNIQUE
        else:
            status = AMBIGUOUS
        return MatchResult(status, "in_person", candidates=cands, source=source, scope=scope, location=loc)
    return MatchResult(UNKNOWN, "not_itemizable")
