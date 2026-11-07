"""Parse Transact mobile-order receipts.

Two input formats share one line-based parser:

* the plain-text transcription (``data/receipts_raw.txt``): blocks separated by ``=== #<txn>``
* real receipt emails (``.eml``, usually multipart with an HTML body), via :func:`parse_eml`

Body layout (after any greeting / forwarding headers)::

    2026-11-05 2:21 PM          datetime
    Target: 2:35 PM             optional
    Gothic Grill                location
    Bryan Center                building
    (address / phone lines)     optional, ignored
    1. Turkey Club Wrap         item
    $12.85                      a bare price prices the line directly above it
         Sweet Potato Fries     sub-item (~5 spaces) / modifier (~8 spaces)
    Subtotal / $x  Tax / $x  Total / $x
    DukeCard / Student Food / $x      or  Board Plan Equivalency $x / 1 Used - $x  or  Amex ****1234 / $x
    Cutlery Needed              optional trailing notes
"""

from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser

from .money import money, receipt_tax

PRICE_RE = re.compile(r"^\$(\d+\.\d{2})$")
INLINE_PRICE_RE = re.compile(r"^(?P<text>.*\S)\s+\$(?P<price>\d+\.\d{2})$")
ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")
SUBJECT_TXN_RE = re.compile(r"#\s*(\d+)\s+Receipt", re.I)
BODY_TXN_RE = re.compile(r"#\s*(\d{6,})")
CARD_BRANDS = ("Amex", "American Express", "Visa", "Mastercard", "MasterCard", "Discover")
DATETIME_FORMATS = (
    "%Y-%m-%d %I:%M %p",
    "%m/%d/%Y %I:%M %p",
    "%B %d, %Y %I:%M %p",
    "%b %d, %Y %I:%M %p",
    "%Y-%m-%d %H:%M",
)
TOTAL_KEYS = ("Subtotal", "Tax", "Total")
STUDENT_FOOD = "Student Food"
BOARD_PLAN = "Board Plan Equivalency"


class ReceiptParseError(ValueError):
    pass


@dataclass
class Line:
    text: str
    level: int  # 0 = item, 1 = sub-item, 2 = modifier
    price: Decimal | None = None


@dataclass
class Item:
    number: int
    name: str
    lines: list[Line] = field(default_factory=list)  # lines[0] is the item itself

    @property
    def priced(self) -> list[Line]:
        return [l for l in self.lines if l.price is not None]

    @property
    def total(self) -> Decimal:
        return sum((l.price for l in self.priced), Decimal("0"))

    @property
    def base(self) -> tuple[str, Decimal]:
        """(config label, price) of the first priced line, i.e. the item's base price."""
        if not self.priced:
            return "", Decimal("0.00")
        first = self.priced[0]
        label = "" if first is self.lines[0] else first.text
        return label, first.price

    @property
    def addons(self) -> list[Line]:
        return self.priced[1:]

    @property
    def modifiers(self) -> list[str]:
        return [l.text for l in self.lines[1:] if l.price is None]


@dataclass
class Receipt:
    txn: str
    when: datetime
    location: str
    building: str
    items: list[Item]
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    tenders: dict[str, Decimal]
    target: str | None = None
    extra_header: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def food_points(self) -> Decimal | None:
        return self.tenders.get(STUDENT_FOOD)

    @property
    def board_swipe(self) -> Decimal | None:
        return self.tenders.get(BOARD_PLAN)

    @property
    def other_tenders(self) -> dict[str, Decimal]:
        return {k: v for k, v in self.tenders.items() if k not in (STUDENT_FOOD, BOARD_PLAN)}

    def arithmetic_errors(self) -> list[str]:
        """Check items -> subtotal -> tax -> total -> payments. Empty list means consistent."""
        errs = []
        items_sum = sum((it.total for it in self.items), Decimal("0"))
        if items_sum != self.subtotal:
            errs.append(f"items sum {items_sum} != subtotal {self.subtotal}")
        expected_tax = receipt_tax(self.subtotal, self.board_swipe or Decimal("0"))
        if expected_tax != self.tax:
            errs.append(f"tax {self.tax} != expected {expected_tax}")
        if self.subtotal + self.tax != self.total:
            errs.append(f"subtotal + tax {self.subtotal + self.tax} != total {self.total}")
        paid = sum(self.tenders.values(), Decimal("0"))
        if paid != self.total:
            errs.append(f"payments {paid} != total {self.total}")
        return errs


# --------------------------------------------------------------------------- line parser
def _parse_datetime(s: str) -> datetime | None:
    s = " ".join(s.split())
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _split_price(s: str) -> tuple[str, Decimal | None]:
    """'$12.85' -> ('', 12.85); 'Guacamole $1.59' -> ('Guacamole', 1.59); 'Arepa' -> ('Arepa', None)."""
    if m := PRICE_RE.match(s):
        return "", money(m.group(1))
    if m := INLINE_PRICE_RE.match(s):
        return m.group("text"), money(m.group("price"))
    return s, None


def parse_receipt_lines(txn: str, lines: list[str]) -> Receipt:
    """Parse one receipt body. Tolerates blank lines, greetings before the datetime line,
    an optional ``Target:`` line and extra address / phone lines before the first item."""
    raw = [l.rstrip() for l in lines if l.strip()]
    start = next((i for i, l in enumerate(raw) if _parse_datetime(l.strip())), None)
    if start is None:
        raise ReceiptParseError(f"#{txn}: no order date/time line found")
    when = _parse_datetime(raw[start].strip())
    i = start + 1

    target = None
    header: list[str] = []
    while i < len(raw) and not ITEM_RE.match(raw[i]):
        s = raw[i].strip()
        if s.split(" ", 1)[0] in TOTAL_KEYS:
            break
        if s.lower().startswith("target"):
            target = s.split(":", 1)[-1].strip()
        else:
            header.append(s)
        i += 1
    if not header:
        raise ReceiptParseError(f"#{txn}: no location line found")
    location = header[0]
    building = header[1] if len(header) > 1 else ""

    items: list[Item] = []
    while i < len(raw) and raw[i].strip().split(" ", 1)[0] != "Subtotal":
        line = raw[i]
        stripped = line.strip()
        if m := ITEM_RE.match(line):
            text, price = _split_price(m.group(2).strip())
            items.append(Item(int(m.group(1)), text, [Line(text, 0, price)]))
        else:
            if not items:
                raise ReceiptParseError(f"#{txn}: line {stripped!r} before the first item")
            text, price = _split_price(stripped)
            if not text:  # bare price: prices the line directly above
                items[-1].lines[-1].price = price
            else:
                indent = len(line) - len(line.lstrip(" "))
                items[-1].lines.append(Line(text, 1 if indent < 8 else 2, price))
        i += 1
    if not items:
        raise ReceiptParseError(f"#{txn}: no items found")

    vals: dict[str, Decimal] = {}
    while i < len(raw) and len(vals) < 3:
        s = raw[i].strip()
        key, _, rest = s.partition(" ")
        if key in TOTAL_KEYS:
            if rest and (m := PRICE_RE.match(rest.strip())):
                vals[key] = money(m.group(1))
                i += 1
            elif i + 1 < len(raw) and (m := PRICE_RE.match(raw[i + 1].strip())):
                vals[key] = money(m.group(1))
                i += 2
            else:
                raise ReceiptParseError(f"#{txn}: {key} has no amount")
            if key == "Total":
                break
        else:
            i += 1
    missing = [k for k in TOTAL_KEYS if k not in vals]
    if missing:
        raise ReceiptParseError(f"#{txn}: missing {', '.join(missing)}")

    tenders: dict[str, Decimal] = {}
    notes: list[str] = []
    rest_lines = [r.strip() for r in raw[i:]]
    j = 0
    while j < len(rest_lines):
        r = rest_lines[j]
        nxt = rest_lines[j + 1] if j + 1 < len(rest_lines) else ""
        label, price = _split_price(r)
        if r == "DukeCard" or re.match(r"^\d+ Used - \$\d+\.\d{2}$", r):
            pass
        elif label.startswith(BOARD_PLAN):
            if price is None and PRICE_RE.match(nxt):
                price = money(nxt[1:])
                j += 1
            if price is not None:
                tenders[BOARD_PLAN] = price
        elif (
            label
            and price is None
            and PRICE_RE.match(nxt)
            and (label == STUDENT_FOOD or label.startswith(CARD_BRANDS))
        ):
            tenders[_tender_key(label)] = money(nxt[1:])
            j += 1
        elif label and price is not None and (label == STUDENT_FOOD or label.startswith(CARD_BRANDS)):
            tenders[_tender_key(label)] = price
        elif r:
            notes.append(r)
        j += 1

    return Receipt(
        txn=txn,
        when=when,
        location=location,
        building=building,
        items=items,
        subtotal=vals["Subtotal"],
        tax=vals["Tax"],
        total=vals["Total"],
        tenders=tenders,
        target=target,
        extra_header=header[2:],
        notes=notes,
    )


def _tender_key(label: str) -> str:
    if label == STUDENT_FOOD:
        return STUDENT_FOOD
    if label.startswith("American Express"):
        return "Amex"
    return label.split(" ")[0]


# --------------------------------------------------------------------------- text transcription
def parse_receipts(text: str) -> list[Receipt]:
    """Parse the ``=== #<txn>`` separated plain-text transcription."""
    blocks = re.split(r"^=== ", text, flags=re.M)[1:]
    out = []
    for b in blocks:
        first, _, body = b.partition("\n")
        out.append(parse_receipt_lines(first.strip().lstrip("#").strip(), body.splitlines()))
    return out


def parse_pasted_receipt(text: str) -> list[Receipt]:
    """A user pasting one or more receipts: either the ``===`` format or a single email body
    (the transaction number is then taken from a ``#123456789`` anywhere in the text)."""
    if re.search(r"^=== ", text, flags=re.M):
        return parse_receipts(text)
    m = SUBJECT_TXN_RE.search(text) or BODY_TXN_RE.search(text)
    if not m:
        raise ReceiptParseError("no receipt number (#123456789) found in pasted text")
    return [parse_receipt_lines(m.group(1), _unquote(text).splitlines())]


# --------------------------------------------------------------------------- .eml
class _HTMLText(HTMLParser):
    BLOCK = {
        "br",
        "p",
        "div",
        "tr",
        "td",
        "th",
        "li",
        "ul",
        "ol",
        "table",
        "tbody",
        "thead",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "header",
        "footer",
        "hr",
    }
    SKIP = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """HTML -> one text line per block / table cell, whitespace collapsed, blank lines dropped."""
    p = _HTMLText()
    p.feed(html)
    p.close()
    lines = (" ".join(l.replace("\xa0", " ").split()) for l in "".join(p.parts).splitlines())
    return "\n".join(l for l in lines if l)


def _unquote(text: str) -> str:
    """Strip '> ' reply/forward quoting."""
    return "\n".join(re.sub(r"^(?:> ?)+", "", l) for l in text.splitlines())


def _receipt_message(msg: EmailMessage) -> EmailMessage:
    """If a forwarded receipt is attached as message/rfc822, use the attached original."""
    for part in msg.walk():
        if part.get_content_type() == "message/rfc822":
            inner = part.get_content()
            if SUBJECT_TXN_RE.search(str(inner.get("Subject", ""))):
                return inner
    return msg


def _bodies(msg: EmailMessage) -> list[str]:
    out = []
    for pref in ("plain", "html"):
        part = msg.get_body(preferencelist=(pref,))
        if part is None:
            continue
        content = part.get_content()
        out.append(_unquote(content) if pref == "plain" else html_to_text(content))
    return out


def parse_eml(data: bytes) -> Receipt:
    """Parse a receipt email (.eml). Tries the text/plain body first, then the HTML body,
    and returns the first parse whose arithmetic checks out (else the first that parsed)."""
    msg = _receipt_message(email.message_from_bytes(data, policy=policy.default))
    subject = str(msg.get("Subject", ""))
    bodies = _bodies(msg)
    if not bodies:
        raise ReceiptParseError("email has no text or HTML body")
    m = SUBJECT_TXN_RE.search(subject)
    txn = m.group(1) if m else None
    parsed: list[Receipt] = []
    errors: list[str] = []
    for body in bodies:
        t = txn
        if t is None and (bm := BODY_TXN_RE.search(body)):
            t = bm.group(1)
        if t is None:
            errors.append("no receipt number in subject or body")
            continue
        try:
            r = parse_receipt_lines(t, body.splitlines())
        except ReceiptParseError as e:
            errors.append(str(e))
            continue
        if not r.arithmetic_errors():
            return r
        parsed.append(r)
    if parsed:
        return parsed[0]
    raise ReceiptParseError("; ".join(errors) or "could not parse receipt email")
