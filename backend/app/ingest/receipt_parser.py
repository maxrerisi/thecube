"""Transact mobile-order receipt (.eml) parser (SPEC 6; format in docs/findings/receipts.md).

Ported from spikes/parse_receipt.py (31/31 receipts). Deterministic, stdlib + pydantic.
"""
import email
import html
import re
from datetime import datetime
from email import policy
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from app.schemas import ParsedItem, ParsedReceipt

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
MONEY = re.compile(r"-?\$(\d+(?:,\d{3})*\.\d{2})")


class NotAReceipt(ValueError):
    pass


def _money(s):
    m = MONEY.search(s or "")
    return float(m.group(1).replace(",", "")) if m else None


def _rows(html_body: str) -> list[list[dict]]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_body, flags=re.S | re.I):
        cells = []
        for attrs, inner in re.findall(r"<td([^>]*)>(.*?)</td>", tr, flags=re.S | re.I):
            raw = html.unescape(re.sub(r"<[^>]+>", "", inner)).replace("\xa0", " ")
            cells.append({"text": raw.strip(), "indented": raw.startswith("    "),
                          "center": "center" in attrs})
        if cells and any(c["text"] for c in cells):
            out.append(cells)
    return out


# "#123 Receipt", also forwarded/replied: "FW: #123 Receipt", "Fwd: Re: #123 Receipt"
SUBJECT = re.compile(r"^\s*(?:(?:fw|fwd|re)\s*:\s*)*#\d+\s+Receipt\b", re.I)
ORDER_ROW = re.compile(r"^#\d+$")


def is_receipt(msg: EmailMessage) -> bool:
    return bool(SUBJECT.match(str(msg["Subject"] or "")))


def _unquote(text: str) -> str:
    """Plain-text forwards quote each line with '> ' and may re-wrap long lines. The receipt
    markup has no meaningful newlines, so drop the quoting and join the lines back up."""
    # only "> " (with the space) is quoting; a bare ">" at line start is markup ("<td\n>Tax")
    return "".join(re.sub(r"^(?:> )+", "", line) for line in text.splitlines())


def _bodies(msg: EmailMessage) -> list[str]:
    """Candidate bodies: HTML first, then text/plain (which, for Transact, is HTML markup too)."""
    out = []
    for kind in ("html", "plain"):
        part = msg.get_body((kind,))
        if part is not None:
            body = part.get_content()
            out.append(body if kind == "html" else _unquote(body))
    return out


def parse_message(msg: EmailMessage) -> ParsedReceipt:
    """Parse a receipt, or a receipt forwarded inline (Outlook/Gmail, HTML or quoted text)."""
    errors = []
    for body in _bodies(msg):
        rows = _rows(body)
        # Forward wrappers add rows (the forward header, a note, a signature): start at the
        # receipt's own "#<order>" row.
        start = next((i for i, r in enumerate(rows) if len(r) == 1 and ORDER_ROW.match(r[0]["text"])), None)
        if start is None:
            errors.append("no #<order> row")
            continue
        return _parse_rows(rows[start:])
    raise NotAReceipt(f"no Transact receipt in message {msg['Subject']!r} ({'; '.join(errors) or 'no body'})")


def _parse_rows(rows: list[list[dict]]) -> ParsedReceipt:
    header = [r[0]["text"] for r in rows if len(r) == 1 or r[0]["center"]]
    placed_local = datetime.strptime(header[1], "%Y-%m-%d %I:%M %p").replace(tzinfo=NY)

    items: list[dict] = []
    totals = {"subtotal": None, "tax": None, "total": None}
    points = swipe_value = 0.0
    swipes = 0
    section = "items"
    for row in rows:
        if section == "done":
            break  # past "Transaction #": anything after is the forwarder's signature etc.
        if row[0]["center"]:
            continue
        label = row[0]["text"]
        right = row[1]["text"] if len(row) > 1 else ""
        amt = _money(right)
        if label in ("Subtotal", "Tax", "Total"):
            totals[label.lower()] = amt
            section = "tenders" if label == "Total" else "totals"
            continue
        if label == "Transaction #":
            section = "done"
            continue
        if section == "items":
            m = re.match(r"(\d+)\.\s*(.+)", label)
            if m and not row[0]["indented"]:
                items.append({"name": m.group(2).strip(), "price": amt, "components": []})
            elif items and label:
                items[-1]["components"].append((label, amt))
        elif section == "tenders":
            if label == "Student Food":
                points += amt or 0
            elif label.startswith("Board Plan"):
                used = re.search(r"(\d+)\s+Used", right)
                swipes += int(used.group(1)) if used else 1
                swipe_value += _money(right) or _money(label) or 0

    parsed_items = []
    for it in items:
        priced = [(n, p) for n, p in it["components"] if p is not None]
        price = it["price"] if it["price"] is not None else sum(p for _, p in priced)
        parsed_items.append(ParsedItem(
            name=it["name"], price=round(price, 2), components=[n for n, _ in it["components"]],
            priced_component=priced[0][0] if it["price"] is None and priced else None))
    if None in totals.values():
        raise ValueError(f"receipt {header[0]}: missing totals {totals}")
    return ParsedReceipt(
        order_number=header[0].lstrip("#"), placed_at=placed_local.astimezone(UTC),
        vendor_raw=header[3], building=header[4], items=parsed_items,
        subtotal=totals["subtotal"], tax=totals["tax"], total=totals["total"],
        points_spent=round(points, 2), swipes_used=swipes, swipe_value=round(swipe_value, 2))


def parse_eml_bytes(raw: bytes) -> list[tuple[ParsedReceipt, bytes]]:
    """A receipt; a receipt forwarded inline (FW:/Fwd:, HTML or quoted text); or a forward
    whose attachments are receipts (message/rfc822 or .eml; one or many).

    Returns (receipt, raw bytes holding it) pairs. Raises NotAReceipt if none found, or
    ValueError if something receipt-shaped doesn't parse.
    """
    msg = email.message_from_bytes(raw, policy=policy.default)
    found = []
    for part in msg.walk():
        inner_raw = None
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload()[0] if part.is_multipart() else part.get_payload()
            inner_raw = inner.as_bytes()
        elif (part.get_filename() or "").lower().endswith(".eml"):
            inner_raw = part.get_payload(decode=True)
        if inner_raw:
            inner_msg = email.message_from_bytes(inner_raw, policy=policy.default)
            if is_receipt(inner_msg):
                found.append((parse_message(inner_msg), inner_raw))
    if found:  # attached receipts win over the forward's own body ("FYI", signature, ...)
        return found
    return [(parse_message(msg), raw)]  # the receipt itself, or forwarded inline
