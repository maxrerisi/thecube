"""Shared (community) price catalog. Contributions carry no user id and only day-level dates."""

from __future__ import annotations

from sqlmodel import Session, select

from dukedining.catalog import ADDON, build_catalog
from dukedining.receipts import Receipt as CoreReceipt

from ..models import Receipt, SharedCatalogEntry, User
from ..money_db import to_cents
from . import recompute


def contribute_pending(session: Session, user: User) -> int:
    """If the user opted in, contribute every receipt not contributed yet (each receipt
    exactly once, so re-imports and toggling the checkbox never double-count)."""
    if not user.share_catalog:
        return 0
    pending = session.exec(
        select(Receipt).where(Receipt.user_id == user.id, Receipt.contributed == False)  # noqa: E712
    ).all()
    if not pending:
        return 0
    txns = {r.txn for r in pending}
    core, _ = recompute.core_receipts(session, user.id)
    n = contribute(session, [r for r in core if r.txn in txns])
    for r in pending:
        r.contributed = True
    session.flush()
    return n


def contribute(session: Session, receipts: list[CoreReceipt]) -> int:
    """Add receipt-verified catalog lines. Call only with receipts that are new for this user,
    so re-importing never double-counts. Returns the number of lines contributed."""
    n = 0
    for e in build_catalog(receipts).values():
        cents = to_cents(e.price)
        is_addon = e.kind == ADDON
        row = session.exec(
            select(SharedCatalogEntry).where(
                SharedCatalogEntry.location == e.location,
                SharedCatalogEntry.item == e.item,
                SharedCatalogEntry.base_price_cents == cents,
                SharedCatalogEntry.is_addon == is_addon,
            )
        ).first()
        first, last = e.first.date(), e.last.date()
        if row is None:
            row = SharedCatalogEntry(
                location=e.location, item=e.item, base_price_cents=cents, is_addon=is_addon,
                first_seen=first, last_seen=last, times_seen=0,
            )  # fmt: skip
            session.add(row)
        row.first_seen = min(row.first_seen, first)
        row.last_seen = max(row.last_seen, last)
        row.times_seen += e.times
        n += 1
    session.flush()
    return n
