"""Database models.

Money is stored as integer cents (convert with app.money_db). Times are naive local Duke time
(America/New_York), exactly as eAccounts and the receipts show them."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

# Match statuses mirror dukedining.matching
MATCH_STATUSES = ("itemized", "unique", "ambiguous", "user_confirmed", "unknown", "not_food")


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


class User(SQLModel, table=True):
    """Single demo user for now; auth would hang off this table."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = "Demo student"
    share_catalog: bool = False  # opted in to contributing to the shared price catalog
    created_at: NaiveDatetime = Field(default_factory=_now)


class ImportBatch(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    kind: str  # "receipts" | "eaccounts"
    created_at: NaiveDatetime = Field(default_factory=_now)
    n_new: int = 0
    n_duplicate: int = 0
    reported_balance_cents: int | None = None  # balance the user typed in from eAccounts, if any


class Receipt(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "txn"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    import_id: int | None = Field(default=None, foreign_key="importbatch.id")
    txn: str
    when: NaiveDatetime
    location: str
    building: str = ""
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    food_points_cents: int | None = None
    board_swipe_cents: int | None = None
    other_tender: str | None = None  # e.g. "Amex"
    other_tender_cents: int | None = None
    arithmetic_ok: bool = True


class ReceiptItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    receipt_id: int = Field(foreign_key="receipt.id", index=True)
    line_no: int
    name: str
    option: str = ""  # the sub-line that carried the base price, e.g. "Large"
    base_price_cents: int
    line_total_cents: int
    addons: list = Field(default_factory=list, sa_column=Column(JSON))  # [[text, cents], ...]
    modifiers: list = Field(default_factory=list, sa_column=Column(JSON))  # [text, ...]


class PurchaseGroup(SQLModel, table=True):
    """One real purchase: one or more eAccounts rows (Food splits, void pairs)."""

    __table_args__ = (UniqueConstraint("user_id", "when", "location", "account_family", "card_last4"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    when: NaiveDatetime
    location: str
    account_family: str
    card_last4: str
    spent_cents: int  # positive = spent
    n_rows: int
    channel: str
    terminal_code: str | None = None


class Transaction(SQLModel, table=True):
    """One eAccounts row."""

    __table_args__ = (UniqueConstraint("user_id", "row_key"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    import_id: int | None = Field(default=None, foreign_key="importbatch.id")
    group_id: int | None = Field(default=None, foreign_key="purchasegroup.id", index=True)
    row_key: str
    when: NaiveDatetime
    account: str
    card_last4: str = Field(max_length=4)
    location: str
    type: str
    amount_cents: int  # signed like eAccounts: negative = spent


class Match(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    group_id: int = Field(foreign_key="purchasegroup.id", unique=True)
    status: str = Field(index=True)
    detail: str = ""
    receipt_id: int | None = Field(default=None, foreign_key="receipt.id")
    location: str | None = None  # catalog location used for in-person matching
    # chosen lines (unique / user_confirmed): [{"location","item","price_cents","kind"}]
    chosen: list = Field(default_factory=list, sa_column=Column(JSON))
    # candidate combos: [[{"location","item","price_cents","kind","variants"}], ...]
    candidates: list = Field(default_factory=list, sa_column=Column(JSON))
    source: str = ""  # own / shared
    scope: str = ""  # here / other locations
    skipped_at: NaiveDatetime | None = None
    updated_at: NaiveDatetime = Field(default_factory=_now)


class UserCatalogEntry(SQLModel, table=True):
    """Derived cache: rebuilt from the user's receipts plus their confirmed answers."""

    __table_args__ = (UniqueConstraint("user_id", "location", "item", "price_cents", "kind"),)
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    location: str
    item: str
    price_cents: int
    kind: str = "item"  # item | addon
    variants: list = Field(default_factory=list, sa_column=Column(JSON))
    times_seen: int = 0
    first_seen: date
    last_seen: date
    source: str = "receipt"  # receipt | user


class SharedCatalogEntry(SQLModel, table=True):
    """Community price catalog. Deliberately holds nothing traceable to a person:
    no user id, no timestamps finer than a day."""

    __table_args__ = (UniqueConstraint("location", "item", "base_price_cents", "is_addon"),)
    id: int | None = Field(default=None, primary_key=True)
    location: str
    item: str
    base_price_cents: int
    is_addon: bool = False
    first_seen: date
    last_seen: date
    times_seen: int = 0


USER_TABLES = (Match, Transaction, PurchaseGroup, ReceiptItem, Receipt, UserCatalogEntry, ImportBatch)
