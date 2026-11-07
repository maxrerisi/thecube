"""Dashboard numbers: balance + reconciliation, burn rate, projection, breakdowns."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from dukedining import matching as M
from dukedining.eaccounts import EARow, food_balance, terminal

from ..models import ImportBatch, Match, PurchaseGroup, Receipt, ReceiptItem, Transaction
from ..money_db import from_cents, to_cents

# Last day Food Points can be spent this term (Duke fall 2026 finals end). Override with
# DUKEDINING_TERM_END=YYYY-MM-DD.
DEFAULT_TERM_END = date(2026, 12, 18)
RECENT_WEEKS = 4
TOP_LOCATIONS = 8
KNOWN = (M.ITEMIZED, M.UNIQUE, M.USER_CONFIRMED)


def term_end() -> date:
    v = os.environ.get("DUKEDINING_TERM_END")
    return date.fromisoformat(v) if v else DEFAULT_TERM_END


@dataclass
class Dashboard:
    has_data: bool = False
    balance_cents: int | None = None
    balance_source: str = ""  # "eAccounts" (typed in at import) or "computed"
    computed_cents: int | None = None
    reported_cents: int | None = None
    reconciled: bool | None = None  # None = nothing to compare against
    as_of: datetime | None = None
    first_deposit: datetime | None = None
    spent_cents: int = 0
    weekly_cents: int = 0  # recent burn rate (last RECENT_WEEKS weeks)
    weekly_all_cents: int = 0  # average since first deposit
    run_out: date | None = None
    term_end: date = field(default_factory=term_end)
    left_at_term_end_cents: int | None = None
    by_location: list[tuple[str, int]] = field(default_factory=list)
    by_week: list[tuple[date, int]] = field(default_factory=list)
    top_items: list[dict] = field(default_factory=list)
    swipes: int = 0
    swipe_value_cents: int = 0
    known_pct: int = 0
    n_purchases: int = 0


def _place(g: PurchaseGroup, m: Match | None, receipt_loc: str | None) -> str:
    if receipt_loc:
        return receipt_loc
    if m is not None and m.location:
        return m.location
    if g.channel == "vending":
        return "Vending"
    if g.channel == "convenience store":
        return "Lobby Shop"
    t = terminal(g.location)
    return t[0] if t else g.location


def _week(d: datetime) -> date:
    return (d - timedelta(days=d.weekday())).date()


def build(session: Session, user_id: int) -> Dashboard:
    d = Dashboard()
    txns = session.exec(select(Transaction).where(Transaction.user_id == user_id)).all()
    if not txns:
        return d
    d.has_data = True
    rows = [
        EARow(t.when, t.account, t.card_last4, t.location, t.type, from_cents(t.amount_cents)) for t in txns
    ]
    computed = food_balance(rows)
    d.computed_cents = to_cents(computed)
    d.as_of = max(t.when for t in txns)
    # the balance typed in with the latest eAccounts import (older ones would be stale)
    batch = session.exec(
        select(ImportBatch)
        .where(ImportBatch.user_id == user_id, ImportBatch.kind == "eaccounts")
        .order_by(ImportBatch.id.desc())
    ).first()
    if batch is not None and batch.reported_balance_cents is not None:
        d.reported_cents = batch.reported_balance_cents
        d.balance_cents, d.balance_source = d.reported_cents, "eAccounts"
        if d.computed_cents is not None:
            d.reconciled = d.computed_cents == d.reported_cents
    elif d.computed_cents is not None:
        d.balance_cents, d.balance_source = d.computed_cents, "computed"

    groups = session.exec(
        select(PurchaseGroup).where(PurchaseGroup.user_id == user_id, PurchaseGroup.account_family == "Food")
    ).all()
    deposits = [g.when for g in groups if g.channel == "deposit"]
    d.first_deposit = min(deposits) if deposits else min(g.when for g in groups) if groups else None
    matches = {m.group_id: m for m in session.exec(select(Match).where(Match.user_id == user_id))}
    receipts = {r.id: r for r in session.exec(select(Receipt).where(Receipt.user_id == user_id))}

    spend = [g for g in groups if g.spent_cents > 0 and g.channel not in ("deposit", "print")]
    d.n_purchases = len(spend)
    d.spent_cents = sum(g.spent_cents for g in spend)
    known = sum(g.spent_cents for g in spend if (m := matches.get(g.id)) and m.status in KNOWN)
    d.known_pct = round(100 * known / d.spent_cents) if d.spent_cents else 0

    # ---- by location
    loc = Counter()
    for g in spend:
        m = matches.get(g.id)
        r = receipts.get(m.receipt_id) if m and m.receipt_id else None
        loc[_place(g, m, r.location if r else None)] += g.spent_cents
    ranked = loc.most_common()
    d.by_location = ranked[:TOP_LOCATIONS]
    if len(ranked) > TOP_LOCATIONS:
        d.by_location.append(("Everywhere else", sum(c for _, c in ranked[TOP_LOCATIONS:])))

    # ---- by week (Mon-start), from the first deposit to the latest transaction
    weekly = defaultdict(int)
    for g in spend:
        weekly[_week(g.when)] += g.spent_cents
    if spend:
        start = _week(d.first_deposit or min(g.when for g in spend))
        end = _week(d.as_of)
        wk = start
        while wk <= end:
            d.by_week.append((wk, weekly.get(wk, 0)))
            wk += timedelta(days=7)

    # ---- burn rate and projection (per day, from the as-of date)
    if spend and d.first_deposit:
        days_all = max((d.as_of - d.first_deposit).days + 1, 1)
        d.weekly_all_cents = round(d.spent_cents * 7 / days_all)
        recent_start = d.as_of - timedelta(days=7 * RECENT_WEEKS)
        recent = sum(g.spent_cents for g in spend if g.when > recent_start)
        span = min(7 * RECENT_WEEKS, days_all)
        d.weekly_cents = round(recent * 7 / span)
        per_day = d.weekly_cents / 7
        if d.balance_cents is not None and per_day > 0:
            d.run_out = (d.as_of + timedelta(days=d.balance_cents / per_day)).date()
            days_left = max((d.term_end - d.as_of.date()).days, 0)
            d.left_at_term_end_cents = round(d.balance_cents - per_day * days_left)

    # ---- top items (receipt items + confirmed / unique in-person answers)
    items: dict[str, dict] = {}

    def bump(name, where, cents):
        e = items.setdefault(name, {"item": name, "count": 0, "cents": 0, "places": Counter()})
        e["count"] += 1
        e["cents"] += cents
        e["places"][where] += 1

    rids = [r.id for r in receipts.values()]
    if rids:
        for it in session.exec(select(ReceiptItem).where(ReceiptItem.receipt_id.in_(rids))):
            bump(it.name, receipts[it.receipt_id].location, it.line_total_cents)
    for m in matches.values():
        if m.status in (M.UNIQUE, M.USER_CONFIRMED) and m.detail == "in_person":
            for line in m.chosen:
                if line["kind"] == "item":
                    bump(line["item"], line["location"], line["price_cents"])
    top = sorted(items.values(), key=lambda e: (-e["count"], -e["cents"], e["item"]))[:10]
    for e in top:
        e["place"] = e.pop("places").most_common(1)[0][0]
    d.top_items = top

    # ---- board swipes vs food points
    swiped = [r for r in receipts.values() if r.board_swipe_cents]
    d.swipes = len(swiped)
    d.swipe_value_cents = sum(r.board_swipe_cents for r in swiped)
    return d
