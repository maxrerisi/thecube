"""T3: parser on all real receipts + bulk-forward .eml."""
from email.message import EmailMessage
from email import policy
import email
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ingest.receipt_parser import NotAReceipt, parse_eml_bytes

EMAILS = sorted((Path(__file__).resolve().parents[2] / "emails").glob("*.eml"))
pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")


def test_all_receipts_parse_and_balance():
    assert len(EMAILS) == 31
    for p in EMAILS:
        [(r, raw)] = parse_eml_bytes(p.read_bytes())
        assert raw == p.read_bytes()
        assert p.name.startswith(f"#{r.order_number} ")
        assert abs(sum(i.price for i in r.items) - r.subtotal) < 0.01, p.name
        assert abs(r.subtotal + r.tax - r.total) < 0.01, p.name
        assert abs(r.points_spent + r.swipe_value - r.total) < 0.01, p.name  # tenders = total
        assert r.placed_at.tzinfo is not None


def test_known_receipt_fields():
    [(r, _)] = parse_eml_bytes(next(p for p in EMAILS if "#125089644" in p.name).read_bytes())
    assert r.vendor_raw == "Sazon" and r.building == "Brodhead Center"
    [it] = r.items
    assert (it.name, it.price, it.priced_component) == ("Arepa Bowl", 12.85, "Hot Honey Chicken")
    assert len(it.components) == 17


def test_swipes_and_timezone():
    swipe_orders = [r for p in EMAILS for r, _ in parse_eml_bytes(p.read_bytes()) if r.swipes_used]
    assert len(swipe_orders) == 11
    assert {r.swipe_value for r in swipe_orders} == {6.10, 11.80}
    [(r, _)] = parse_eml_bytes(EMAILS[0].read_bytes())
    # local EDT (UTC-4) in Aug-Oct
    assert r.placed_at.utcoffset().total_seconds() == 0


def test_bulk_forward_with_rfc822_attachments():
    fwd = EmailMessage(policy=policy.default)
    fwd["Subject"] = "Fw: receipts"
    fwd["From"] = "someone@example.com"
    fwd.set_content("see attached")
    for p in EMAILS[:3]:
        fwd.add_attachment(email.message_from_bytes(p.read_bytes(), policy=policy.default))
    got = parse_eml_bytes(fwd.as_bytes())
    assert [r.order_number for r, _ in got] == [p.name.split()[0].lstrip("#") for p in EMAILS[:3]]


def test_not_a_receipt():
    m = EmailMessage()
    m["Subject"] = "hello"
    m.set_content("hi")
    with pytest.raises(NotAReceipt):
        parse_eml_bytes(m.as_bytes())
