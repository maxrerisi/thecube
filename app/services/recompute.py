"""Derived state: purchase groups, the user's catalog, and matches.

Everything here is recomputable from the user's raw imports (receipts, eAccounts rows) plus
their confirmed answers, so re-running it is always safe."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, delete, select

from dukedining import catalog as core_catalog
from dukedining import matching as M
from dukedining.eaccounts import EARow, Purchase, group_purchases, terminal
from dukedining.receipts import BOARD_PLAN, STUDENT_FOOD, Item, Line
from dukedining.receipts import Receipt as CoreReceipt

from ..models import (
    Match,
    PurchaseGroup,
    Receipt,
    ReceiptItem,
    SharedCatalogEntry,
    Transaction,
    UserCatalogEntry,
)
from ..money_db import from_cents, to_cents

MAX_STORED_CANDIDATES = 12
REVIEW_STATUSES = (M.AMBIGUOUS, M.UNKNOWN)


# --------------------------------------------------------------------------- conversions
def core_receipts(session: Session, user_id: int) -> tuple[list[CoreReceipt], dict[str, int]]:
    """DB receipts -> dukedining Receipt objects, plus txn -> receipt.id."""
    rows = session.exec(select(Receipt).where(Receipt.user_id == user_id).order_by(Receipt.when)).all()
    ids = [r.id for r in rows]
    items_by: dict[int, list[ReceiptItem]] = {i: [] for i in ids}
    if ids:
        for it in session.exec(
            select(ReceiptItem).where(ReceiptItem.receipt_id.in_(ids)).order_by(ReceiptItem.line_no)
        ):
            items_by[it.receipt_id].append(it)
    out = []
    for r in rows:
        items = []
        for it in items_by[r.id]:
            base = from_cents(it.base_price_cents)
            unpriced = it.base_price_cents == 0 and not it.option and not it.addons
            lines = [Line(it.name, 0, None if (it.option or unpriced) else base)]
            if it.option:
                lines.append(Line(it.option, 1, base))
            lines += [Line(text, 1, from_cents(c)) for text, c in it.addons]
            lines += [Line(text, 2) for text in it.modifiers]
            items.append(Item(it.line_no, it.name, lines))
        tenders = {}
        if r.food_points_cents is not None:
            tenders[STUDENT_FOOD] = from_cents(r.food_points_cents)
        if r.board_swipe_cents is not None:
            tenders[BOARD_PLAN] = from_cents(r.board_swipe_cents)
        if r.other_tender:
            tenders[r.other_tender] = from_cents(r.other_tender_cents)
        out.append(CoreReceipt(
            r.txn, r.when, r.location, r.building, items,
            from_cents(r.subtotal_cents), from_cents(r.tax_cents), from_cents(r.total_cents), tenders,
        ))  # fmt: skip
    return out, {r.txn: r.id for r in rows}


def group_to_purchase(g: PurchaseGroup) -> Purchase:
    return Purchase(g.when, g.location, g.account_family, g.card_last4, from_cents(g.spent_cents))


def entry_to_json(e: core_catalog.CatalogEntry) -> dict:
    return {
        "location": e.location,
        "item": e.item,
        "price_cents": to_cents(e.price),
        "kind": e.kind,
        "variants": sorted(e.variants),
        "times": e.times,
        "source": e.source,
    }


def user_pool(session: Session, user_id: int) -> list[core_catalog.CatalogEntry]:
    rows = session.exec(
        select(UserCatalogEntry).where(UserCatalogEntry.user_id == user_id).order_by(UserCatalogEntry.id)
    ).all()
    return [
        core_catalog.CatalogEntry(
            e.location,
            e.item,
            from_cents(e.price_cents),
            set(e.variants),
            e.kind,
            e.times_seen,
            datetime.combine(e.last_seen, datetime.min.time()),
            datetime.combine(e.first_seen, datetime.min.time()),
            e.source,
        )  # fmt: skip
        for e in rows
    ]


def shared_pool(session: Session) -> list[core_catalog.CatalogEntry]:
    rows = session.exec(select(SharedCatalogEntry).order_by(SharedCatalogEntry.id)).all()
    return [
        core_catalog.CatalogEntry(
            e.location,
            e.item,
            from_cents(e.base_price_cents),
            kind=core_catalog.ADDON if e.is_addon else core_catalog.ITEM,
            times=e.times_seen,
            source="shared",
        )  # fmt: skip
        for e in rows
    ]


# --------------------------------------------------------------------------- groups
def regroup(session: Session, user_id: int) -> None:
    """(Re)build purchase groups from all of the user's eAccounts rows."""
    txns = session.exec(
        select(Transaction).where(Transaction.user_id == user_id).order_by(Transaction.id)
    ).all()
    core_rows = [
        EARow(t.when, t.account, t.card_last4, t.location, t.type, from_cents(t.amount_cents)) for t in txns
    ]
    by_obj = {id(r): t for r, t in zip(core_rows, txns, strict=True)}
    existing = {
        (g.when, g.location, g.account_family, g.card_last4): g
        for g in session.exec(select(PurchaseGroup).where(PurchaseGroup.user_id == user_id))
    }
    for p in group_purchases(core_rows):
        key = (p.when, p.location, p.account, p.card_last4)
        spent = to_cents(p.spent)
        g = existing.get(key)
        if g is None:
            t = terminal(p.location)
            g = PurchaseGroup(
                user_id=user_id, when=p.when, location=p.location, account_family=p.account,
                card_last4=p.card_last4, spent_cents=spent, n_rows=p.n_rows, channel=p.channel,
                terminal_code=t[1] if t else None,
            )  # fmt: skip
            session.add(g)
            session.flush()
        elif g.spent_cents != spent or g.n_rows != p.n_rows:
            # more rows of this purchase arrived (e.g. the other half of a Food split): re-match it
            g.spent_cents, g.n_rows, g.channel = spent, p.n_rows, p.channel
            session.exec(delete(Match).where(Match.group_id == g.id))
        for r in p.rows:
            by_obj[id(r)].group_id = g.id
    session.flush()


# --------------------------------------------------------------------------- catalog
def rebuild_user_catalog(session: Session, user_id: int) -> None:
    """User catalog = lines from their receipts + lines from their confirmed answers."""
    receipts, _ = core_receipts(session, user_id)
    cat = core_catalog.build_catalog(receipts)
    confirmed = session.exec(
        select(Match, PurchaseGroup)
        .join(PurchaseGroup, Match.group_id == PurchaseGroup.id)
        .where(Match.user_id == user_id, Match.status == M.USER_CONFIRMED)
    ).all()
    for m, g in confirmed:
        for line in m.chosen:
            price = from_cents(line["price_cents"])
            key = (line["location"], line["item"], price, line["kind"])
            e = cat.get(key)
            if e is None:
                e = cat[key] = core_catalog.CatalogEntry(
                    line["location"], line["item"], price, kind=line["kind"], source="user"
                )
            e.times += 1
            e.last = max(e.last or g.when, g.when)
            e.first = min(e.first or g.when, g.when)
    session.exec(delete(UserCatalogEntry).where(UserCatalogEntry.user_id == user_id))
    for e in cat.values():
        session.add(UserCatalogEntry(
            user_id=user_id, location=e.location, item=e.item, price_cents=to_cents(e.price),
            kind=e.kind, variants=sorted(e.variants), times_seen=e.times,
            first_seen=e.first.date(), last_seen=e.last.date(), source=e.source,
        ))  # fmt: skip
    session.flush()


# --------------------------------------------------------------------------- matches
@dataclass
class MatchStats:
    counts: Counter
    need_review: int


def rematch(session: Session, user_id: int) -> MatchStats:
    """Recompute every match that the user hasn't confirmed."""
    receipts, receipt_ids = core_receipts(session, user_id)
    groups = session.exec(
        select(PurchaseGroup).where(PurchaseGroup.user_id == user_id).order_by(PurchaseGroup.when)
    ).all()
    purchases = [group_to_purchase(g) for g in groups]
    alias = M.learn_location_aliases(purchases, receipts)
    pools = [(M.OWN, user_pool(session, user_id)), (M.SHARED, shared_pool(session))]
    existing = {m.group_id: m for m in session.exec(select(Match).where(Match.user_id == user_id))}

    for g, p in zip(groups, purchases, strict=True):
        m = existing.get(g.id)
        if m is not None and m.status == M.USER_CONFIRMED:
            continue
        r = M.classify(p, receipts, alias, pools)
        if m is None:
            m = Match(user_id=user_id, group_id=g.id, status=r.status)
            session.add(m)
        cands = [[entry_to_json(e) for e in combo] for combo in r.candidates[:MAX_STORED_CANDIDATES]]
        m.status, m.detail = r.status, r.detail
        m.receipt_id = receipt_ids.get(r.receipt.txn) if r.receipt else None
        m.location, m.source, m.scope = r.location, r.source, r.scope
        m.candidates = cands
        m.chosen = cands[0] if r.status == M.UNIQUE else []
        m.updated_at = datetime.now().replace(microsecond=0)
    session.flush()
    return stats(session, user_id)


def stats(session: Session, user_id: int) -> MatchStats:
    ms = session.exec(select(Match).where(Match.user_id == user_id)).all()
    counts = Counter(m.status for m in ms)
    need = sum(1 for m in ms if m.status in REVIEW_STATUSES and m.detail == "in_person")
    return MatchStats(counts, need)


def refresh(session: Session, user_id: int) -> MatchStats:
    """Full recompute after any import or answer."""
    regroup(session, user_id)
    rebuild_user_catalog(session, user_id)
    return rematch(session, user_id)
