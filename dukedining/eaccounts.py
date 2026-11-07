"""eAccounts (DukeCard portal) transactions: parsing, purchase grouping, reconciliation.

Data only ever comes from the user: the CSV schema of ``data/eaccounts_raw.csv`` or the
Account Transactions table copied from the eAccounts page (tab-separated text).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .money import ZERO, money

# Location strings look like "Gothic Grill GOTWeb1" / "Il Forno ILFReg1" / "Its Thyme THYKsk1"
TERMINAL_RE = re.compile(r"^(?P<name>.*?)\s+(?P<code>[A-Z]{3})(?P<kind>Web|Reg|Ksk)(?P<n>\d+)$")
KIND_CHANNEL = {"Web": "mobile order", "Reg": "register", "Ksk": "kiosk"}
FOOD = "Food"
DATETIME_FORMATS = ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M %p")
PASTE_COLUMNS = ("Date/Time", "Account Name", "Card Number", "Location", "Transaction Type", "Amount")


class EAccountsParseError(ValueError):
    pass


@dataclass(frozen=True)
class EARow:
    when: datetime
    account: str
    card_last4: str
    location: str
    type: str
    amount: Decimal  # signed as eAccounts shows it: negative = money spent

    @property
    def family(self) -> str:
        return FOOD if self.account.startswith(FOOD) else self.account


@dataclass
class Purchase:
    """One real-world purchase: one or more eAccounts rows."""

    when: datetime
    location: str
    account: str  # account family ("Food" for Food / Food - Orientation)
    card_last4: str
    spent: Decimal  # positive = money spent; negative = deposit/credit; 0 = voided
    rows: list[EARow] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def accounts(self) -> str:
        return "+".join(sorted({r.account for r in self.rows}))

    @property
    def channel(self) -> str:
        return channel_of(self.location, self.account, -self.spent)

    @property
    def terminal(self) -> tuple[str, str, str] | None:
        return terminal(self.location)


# --------------------------------------------------------------------------- field parsing
def last4(card: str) -> str:
    """Only ever keep the last 4 digits of a card number."""
    digits = re.sub(r"\D", "", card or "")
    return digits[-4:]


def parse_amount(s: str) -> Decimal:
    """'(13.81) USD' -> -13.81, '1,023.00 USD' -> 1023.00, '-13.81' -> -13.81."""
    t = s.strip().upper().replace("USD", "").replace("$", "").strip()
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    try:
        v = money(t)
    except InvalidOperation as e:
        raise EAccountsParseError(f"bad amount {s!r}") from e
    return -v if neg else v


def parse_datetime(s: str) -> datetime:
    s = " ".join(s.split())
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise EAccountsParseError(f"bad date/time {s!r}")


def terminal(location: str) -> tuple[str, str, str] | None:
    """'Il Forno ILFReg1' -> ('Il Forno', 'ILF', 'Reg')."""
    m = TERMINAL_RE.match(location)
    return (m.group("name"), m.group("code"), m.group("kind")) if m else None


def channel_of(location: str, account: str, amount: Decimal) -> str:
    """amount: signed like eAccounts (positive = credit)."""
    if account == "ePrint":
        return "print"
    if amount > 0 and location.startswith("DukeCard Offices"):
        return "deposit"
    if location.startswith("Vending"):
        return "vending"
    if location.startswith("Lobby Shop"):
        return "convenience store"
    t = terminal(location)
    if t:
        return KIND_CHANNEL[t[2]]
    return "other"


# --------------------------------------------------------------------------- loaders
def load_csv(text: str) -> list[EARow]:
    """CSV with columns datetime,account,card_last4,location,type,amount."""
    rows = []
    for n, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            rows.append(
                EARow(
                    when=parse_datetime(r["datetime"]),
                    account=r["account"].strip(),
                    card_last4=last4(r["card_last4"]),
                    location=r["location"].strip(),
                    type=r["type"].strip(),
                    amount=money(r["amount"]),
                )
            )
        except (KeyError, InvalidOperation, EAccountsParseError) as e:
            raise EAccountsParseError(f"CSV line {n}: {e}") from e
    return rows


def parse_paste(text: str) -> list[EARow]:
    """Text copied from the eAccounts Account Transactions table.

    Normally tab-separated, one row per line, optionally with the header row. Some browsers
    copy one cell per line instead; that layout is handled too."""
    lines = [l for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    if not lines:
        return []
    if any("\t" in l for l in lines):
        cells = [[c.strip() for c in l.split("\t")] for l in lines]
        cells = [[c for c in row if c] for row in cells]
    else:
        flat = [l.strip() for l in lines]
        if flat[: len(PASTE_COLUMNS)] == list(PASTE_COLUMNS):
            flat = flat[len(PASTE_COLUMNS) :]
        if len(flat) % len(PASTE_COLUMNS):
            raise EAccountsParseError("couldn't split pasted text into 6-column rows; copy the table again")
        cells = [flat[i : i + 6] for i in range(0, len(flat), 6)]

    rows = []
    for n, row in enumerate(cells, start=1):
        if not row or row[0] in ("Date/Time", "Date"):
            continue  # header
        if len(row) != 6:
            raise EAccountsParseError(f"row {n}: expected 6 columns, got {len(row)}: {row!r}")
        dt, account, card, location, typ, amount = row
        rows.append(EARow(parse_datetime(dt), account, last4(card), location, typ, parse_amount(amount)))
    return rows


def parse_any(text: str) -> list[EARow]:
    """CSV (with the datetime,account,... header) or a pasted table."""
    first = text.lstrip().split("\n", 1)[0]
    if first.replace(" ", "").lower().startswith("datetime,account"):
        return load_csv(text)
    return parse_paste(text)


# --------------------------------------------------------------------------- identity / grouping
def row_keys(rows: list[EARow]) -> list[str]:
    """Stable idempotency key per row: hash of datetime + location + amount + the row's
    position among identical (datetime, location, amount) rows in this import.

    Using the position among *identical* rows (not the absolute row number) means re-pasting
    a longer table with newer rows on top still yields the same keys for old rows."""
    seen: dict[tuple, int] = defaultdict(int)
    keys = []
    for r in rows:
        base = (r.when.strftime("%Y-%m-%d %H:%M"), r.location, str(r.amount))
        idx = seen[base]
        seen[base] += 1
        keys.append(hashlib.sha256("|".join((*base, str(idx))).encode()).hexdigest()[:32])
    return keys


def group_purchases(rows: list[EARow]) -> list[Purchase]:
    """Collapse rows that are one purchase: splits across Food / Food - Orientation in the
    same minute, and $0.10 debit/credit pairs that cancel within the same minute (net 0)."""
    groups: dict[tuple, list[EARow]] = defaultdict(list)
    for r in rows:
        groups[(r.when, r.location, r.family, r.card_last4)].append(r)
    out = [
        Purchase(when, loc, fam, card, -sum((r.amount for r in rs), ZERO), list(rs))
        for (when, loc, fam, card), rs in groups.items()
    ]
    return sorted(out, key=lambda p: p.when)


def food_balance(rows: list[EARow]) -> Decimal | None:
    """Sum of all Food* rows since the first deposit. When the data is complete this equals
    the balance eAccounts shows. None if there's no deposit in the data."""
    food = [r for r in rows if r.family == FOOD]
    deposits = [r.when for r in food if channel_of(r.location, r.family, r.amount) == "deposit"]
    if not deposits:
        return None
    first = min(deposits)
    return sum((r.amount for r in food if r.when >= first), ZERO)
