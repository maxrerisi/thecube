"""Idempotent imports. Receipts are keyed on (user, txn); eAccounts rows on (user, row_key)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, select

from dukedining.eaccounts import EAccountsParseError, EARow, parse_any, row_keys
from dukedining.receipts import Receipt as CoreReceipt
from dukedining.receipts import ReceiptParseError, parse_eml, parse_pasted_receipt

from ..models import ImportBatch, Receipt, ReceiptItem, Transaction, User
from ..money_db import to_cents
from . import recompute, shared


@dataclass
class ImportSummary:
    kind: str
    new: int = 0
    duplicate: int = 0
    need_review: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- parsing user input
def parse_receipt_inputs(
    files: list[tuple[str, bytes]], pasted: str = ""
) -> tuple[list[CoreReceipt], list[str]]:
    """Uploaded .eml / .txt files and/or pasted text -> receipts (deduplicated by txn) + errors."""
    out: dict[str, CoreReceipt] = {}
    errors: list[str] = []

    def keep(rs):
        for r in rs:
            out.setdefault(r.txn, r)

    for name, data in files:
        if not data:
            continue
        try:
            if name.lower().endswith(".eml"):
                keep([parse_eml(data)])
            else:
                keep(parse_pasted_receipt(data.decode("utf-8", errors="replace")))
        except ReceiptParseError as e:
            errors.append(f"{name}: {e}")
    if pasted.strip():
        try:
            keep(parse_pasted_receipt(pasted))
        except ReceiptParseError as e:
            errors.append(f"pasted text: {e}")
    return list(out.values()), errors


def parse_eaccounts_input(text: str) -> tuple[list[EARow], list[str]]:
    if not text.strip():
        return [], []
    try:
        return parse_any(text), []
    except EAccountsParseError as e:
        return [], [str(e)]


# --------------------------------------------------------------------------- imports
def import_receipts(
    session: Session, user: User, receipts: list[CoreReceipt], errors: list[str] | None = None
) -> ImportSummary:
    summary = ImportSummary("receipts", errors=list(errors or []))
    existing = set(session.exec(select(Receipt.txn).where(Receipt.user_id == user.id)).all())
    batch = ImportBatch(user_id=user.id, kind="receipts")
    session.add(batch)
    session.flush()
    for r in receipts:
        if r.txn in existing:
            summary.duplicate += 1
            continue
        existing.add(r.txn)
        problems = r.arithmetic_errors()
        if problems:
            summary.warnings.append(f"#{r.txn}: {'; '.join(problems)}")
        other = r.other_tenders
        other_name, other_amt = next(iter(other.items()), (None, None))
        row = Receipt(
            user_id=user.id, import_id=batch.id, txn=r.txn, when=r.when, location=r.location,
            building=r.building, subtotal_cents=to_cents(r.subtotal), tax_cents=to_cents(r.tax),
            total_cents=to_cents(r.total), food_points_cents=to_cents(r.food_points),
            board_swipe_cents=to_cents(r.board_swipe), other_tender=other_name,
            other_tender_cents=to_cents(other_amt), arithmetic_ok=not problems,
        )  # fmt: skip
        session.add(row)
        session.flush()
        for it in r.items:
            option, base = it.base
            session.add(ReceiptItem(
                receipt_id=row.id, line_no=it.number, name=it.name, option=option,
                base_price_cents=to_cents(base), line_total_cents=to_cents(it.total),
                addons=[[a.text, to_cents(a.price)] for a in it.addons], modifiers=it.modifiers,
            ))  # fmt: skip
        summary.new += 1
    batch.n_new, batch.n_duplicate = summary.new, summary.duplicate
    session.flush()
    shared.contribute_pending(session, user)
    summary.need_review = recompute.refresh(session, user.id).need_review
    session.commit()
    return summary


def import_eaccounts(
    session: Session,
    user: User,
    rows: list[EARow],
    reported_balance: Decimal | None = None,
    errors: list[str] | None = None,
) -> ImportSummary:
    summary = ImportSummary("eaccounts", errors=list(errors or []))
    batch = ImportBatch(user_id=user.id, kind="eaccounts", reported_balance_cents=to_cents(reported_balance))
    session.add(batch)
    session.flush()
    existing = set(session.exec(select(Transaction.row_key).where(Transaction.user_id == user.id)).all())
    for r, key in zip(rows, row_keys(rows), strict=True):
        if key in existing:
            summary.duplicate += 1
            continue
        existing.add(key)
        session.add(Transaction(
            user_id=user.id, import_id=batch.id, row_key=key, when=r.when, account=r.account,
            card_last4=r.card_last4[-4:], location=r.location, type=r.type,
            amount_cents=to_cents(r.amount),
        ))  # fmt: skip
        summary.new += 1
    batch.n_new, batch.n_duplicate = summary.new, summary.duplicate
    session.flush()
    summary.need_review = recompute.refresh(session, user.id).need_review
    session.commit()
    return summary
