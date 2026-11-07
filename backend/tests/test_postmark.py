"""T12: Postmark inbound -> receipt lands for the user who owns the sender address (no network;
simulated payloads). William's Duke address belongs to Blue Devil (user 2) for the pitch."""
import base64
import email
from email import policy

import pytest

from app.db import connect
from conftest import AUTH
from test_forwards import EMAILS, SAMPLES, forward_html

pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")
BASIC = ("postmark", "s3cret")


@pytest.fixture
def pm(menus, monkeypatch):
    monkeypatch.setenv("POSTMARK_WEBHOOK_USER", BASIC[0])
    monkeypatch.setenv("POSTMARK_WEBHOOK_PASS", BASIC[1])
    with connect() as conn:
        conn.execute("DELETE FROM orders")
        william = conn.execute("SELECT email FROM users WHERE name = 'Blue Devil'").fetchone()["email"]
    return menus, william


def inline_payload(p, sender):
    """What Postmark POSTs for an Outlook 'Forward' of a receipt."""
    m = email.message_from_bytes(forward_html(p), policy=policy.default)
    return {"From": f"William <{sender}>", "FromFull": {"Email": sender, "Name": "William"},
            "Subject": str(m["Subject"]), "HtmlBody": m.get_body(("html",)).get_content(),
            "TextBody": m.get_body(("plain",)).get_content(), "Attachments": []}


def test_inline_forward_lands_then_duplicate(pm):
    client, william = pm
    assert william, "the address comes from the receipts' To: header"
    body = inline_payload(SAMPLES[1], william)
    assert client.post("/ingest/postmark", json=body).status_code == 401              # no basic auth
    assert client.post("/ingest/postmark", json=body, auth=("x", "y")).status_code == 401
    r = client.post("/ingest/postmark", json=body, auth=BASIC).json()
    assert r["status"] == "ok" and r["imported"] == 1 and r["user_id"] == 2
    assert client.post("/ingest/postmark", json=body, auth=BASIC).json()["duplicates"] == 1
    t = client.get("/today?user_id=2", headers=AUTH)  # shows up via the normal pipeline
    assert t.status_code == 200


def test_attachment_forward(pm):
    client, william = pm
    raw = SAMPLES[2].read_bytes()
    body = {"From": william, "FromFull": {"Email": william.upper()}, "Subject": "FW: receipt", "HtmlBody": "<p>fyi</p>",
            "TextBody": "fyi", "Attachments": [{"Name": "receipt.eml", "ContentType": "message/rfc822",
                                                "Content": base64.b64encode(raw).decode()}]}
    r = client.post("/ingest/postmark", json=body, auth=BASIC).json()
    assert r["status"] == "ok" and r["imported"] == 1


def test_alias_sender_lands_on_blue_devil_and_non_receipt_ignored(pm):
    client, william = pm
    # Outlook may send from an alias (william.z@) rather than the NetID address on the receipts
    r = client.post("/ingest/postmark", json=inline_payload(SAMPLES[0], "william.z@duke.edu"), auth=BASIC).json()
    assert r["status"] == "ok" and r["user_id"] == 2 and r["imported"] == 1
    r = client.post("/ingest/postmark", json={"From": william, "Subject": "lunch?", "TextBody": "hi"}, auth=BASIC)
    assert r.status_code == 200 and r.json()["status"] == "ignored"
