"""Rows for the purchases list: every purchase with its match status and what it was."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from dukedining import matching as M

from ..models import Match, PurchaseGroup, Receipt, ReceiptItem
from ..money_db import fmt

STATUS_LABEL = {
    M.ITEMIZED: "itemized",
    M.UNIQUE: "best match",
    M.AMBIGUOUS: "pick one",
    M.USER_CONFIRMED: "you said",
    M.UNKNOWN: "unknown",
    M.NOT_FOOD: "not food",
}
DETAIL_TEXT = {
    "void": "Voided / retried swipe (cancels out)",
    "deposit": "Deposit",
    "print": "Printing",
    "swipe_remainder": "Board swipe remainder or retry",
    "receipt_missing": "Mobile order (receipt not imported yet)",
    "not_itemizable": "Not itemizable",
}


@dataclass
class Row:
    group: PurchaseGroup
    match: Match | None
    label: str
    what: str
    place: str
    reviewable: bool


def _items_text(items: list[ReceiptItem]) -> str:
    return "; ".join(f"{i.name}" + (f" ({i.option})" if i.option else "") for i in items)


def _combo_text(lines: list[dict]) -> str:
    return " + ".join(f"{l['item']} {fmt(l['price_cents'])}" for l in lines)


def rows(session: Session, user_id: int, show: str = "food") -> list[Row]:
    groups = session.exec(
        select(PurchaseGroup).where(PurchaseGroup.user_id == user_id).order_by(PurchaseGroup.when.desc())
    ).all()
    matches = {m.group_id: m for m in session.exec(select(Match).where(Match.user_id == user_id))}
    receipts = {r.id: r for r in session.exec(select(Receipt).where(Receipt.user_id == user_id))}
    items: dict[int, list[ReceiptItem]] = {}
    if receipts:
        for it in session.exec(
            select(ReceiptItem)
            .where(ReceiptItem.receipt_id.in_(list(receipts)))
            .order_by(ReceiptItem.line_no)
        ):
            items.setdefault(it.receipt_id, []).append(it)

    out = []
    for g in groups:
        m = matches.get(g.id)
        status = m.status if m else ""
        if show == "food" and (status == M.NOT_FOOD or g.account_family != "Food"):
            continue
        if show == "review" and not (m and m.detail == "in_person" and status in (M.AMBIGUOUS, M.UNKNOWN)):
            continue
        place = m.location if m and m.location else g.location
        if m is None:
            what = ""
        elif status == M.ITEMIZED:
            r = receipts.get(m.receipt_id)
            place = r.location if r else place
            what = _items_text(items.get(m.receipt_id, []))
            if r and r.board_swipe_cents:
                what += f" · board swipe covered {fmt(r.board_swipe_cents)}"
        elif status in (M.UNIQUE, M.USER_CONFIRMED):
            what = _combo_text(m.chosen)
        elif status == M.AMBIGUOUS:
            what = f"{len(m.candidates)} possibilities, e.g. {_combo_text(m.candidates[0])}"
        elif m.detail == "in_person":
            what = "No match yet"
        else:
            what = DETAIL_TEXT.get(m.detail, m.detail)
        out.append(
            Row(g, m, STATUS_LABEL.get(status, status), what, place, bool(m and m.detail == "in_person"))
        )
    return out
