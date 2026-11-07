"""The review queue: in-person charges we couldn't pin down, answered one at a time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from dukedining import matching as M
from dukedining.money import money, pretax_for

from ..models import Match, PurchaseGroup, User
from ..money_db import from_cents, to_cents
from . import recompute


class ReviewError(ValueError):
    pass


@dataclass
class Card:
    match: Match
    group: PurchaseGroup


def _in_review(m: Match) -> bool:
    return m.status in recompute.REVIEW_STATUSES and m.detail == "in_person"


def queue(session: Session, user_id: int, include_skipped: bool = False) -> list[Card]:
    """Unanswered in-person charges, oldest first; skipped ones only when asked (at the end)."""
    rows = session.exec(
        select(Match, PurchaseGroup)
        .join(PurchaseGroup, Match.group_id == PurchaseGroup.id)
        .where(Match.user_id == user_id, Match.detail == "in_person")
        .where(Match.status.in_(recompute.REVIEW_STATUSES))
        .order_by(PurchaseGroup.when)
    ).all()
    fresh = [Card(m, g) for m, g in rows if m.skipped_at is None]
    skipped = sorted(
        (Card(m, g) for m, g in rows if m.skipped_at is not None), key=lambda c: c.match.skipped_at
    )
    return fresh + skipped if include_skipped else fresh


def counts(session: Session, user_id: int) -> dict:
    ms = session.exec(select(Match).where(Match.user_id == user_id, Match.detail == "in_person")).all()
    pending = [m for m in ms if _in_review(m)]
    return {
        "left": sum(1 for m in pending if m.skipped_at is None),
        "skipped": sum(1 for m in pending if m.skipped_at is not None),
        "confirmed": sum(1 for m in ms if m.status == M.USER_CONFIRMED),
        "in_person": len(ms),
    }


def card_for(session: Session, user_id: int, group_id: int) -> Card:
    row = session.exec(
        select(Match, PurchaseGroup)
        .join(PurchaseGroup, Match.group_id == PurchaseGroup.id)
        .where(Match.user_id == user_id, PurchaseGroup.id == group_id)
    ).first()
    if row is None or row[0].detail != "in_person":
        raise ReviewError("That charge can't be reviewed.")
    return Card(*row)


def suggested_price(group: PurchaseGroup) -> Decimal:
    return pretax_for(from_cents(group.spent_cents))


@dataclass
class AnswerResult:
    action: str  # confirmed / skipped
    also_resolved: int  # other charges that left the queue because of this answer


def answer(
    session: Session,
    user: User,
    group_id: int,
    choice: str,
    other_name: str = "",
    other_price: str = "",
) -> AnswerResult:
    """choice: 'c<N>' (candidate N), 'other' (with other_name / optional other_price), or 'skip'."""
    card = card_for(session, user.id, group_id)
    m, g = card.match, card.group
    now = datetime.now().replace(microsecond=0)
    if choice == "skip":
        m.skipped_at = now
        session.commit()
        return AnswerResult("skipped", 0)

    if choice.startswith("c") and choice[1:].isdigit():
        idx = int(choice[1:])
        if idx >= len(m.candidates):
            raise ReviewError("That option is no longer available.")
        chosen = [
            {k: line[k] for k in ("location", "item", "price_cents", "kind")} for line in m.candidates[idx]
        ]
    elif choice == "other":
        name = " ".join(other_name.split())
        if not name:
            raise ReviewError("Tell us what you got.")
        if other_price.strip():
            try:
                price = money(other_price)
            except InvalidOperation as e:
                raise ReviewError("Price should look like 7.25") from e
            if price <= 0:
                raise ReviewError("Price should be more than $0.")
        else:
            price = suggested_price(g)
        location = m.location or g.location
        chosen = [{"location": location, "item": name, "price_cents": to_cents(price), "kind": "item"}]
    else:
        raise ReviewError("Pick an option.")

    before = {c.group.id for c in queue(session, user.id, include_skipped=True)} - {g.id}
    m.status, m.chosen, m.skipped_at, m.updated_at = M.USER_CONFIRMED, chosen, None, now
    session.flush()
    recompute.refresh(session, user.id)  # new catalog lines can resolve other charges
    after = {c.group.id for c in queue(session, user.id, include_skipped=True)}
    session.commit()
    return AnswerResult("confirmed", len(before - after))


def unconfirm(session: Session, user: User, group_id: int) -> None:
    """Undo an answer: the charge goes back to automatic matching."""
    card = card_for(session, user.id, group_id)
    if card.match.status == M.USER_CONFIRMED:
        card.match.status, card.match.chosen = M.UNKNOWN, []
        session.flush()
        recompute.refresh(session, user.id)
        session.commit()
