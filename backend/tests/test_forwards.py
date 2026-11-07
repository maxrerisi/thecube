"""Forwarded receipts (the live demo: William forwards a receipt from Outlook).

Fixtures are built from the real receipts in emails/, wrapped the way mail clients
forward: Outlook/Gmail HTML inline, plain-text quoted inline (re-wrapped at 76 cols),
and as an attachment. Each must parse to exactly what the original parses to.
"""
import email
import textwrap
from email import policy
from email.message import EmailMessage
from pathlib import Path

import pytest

from app.ingest.receipt_parser import NotAReceipt, parse_eml_bytes

EMAILS = sorted((Path(__file__).resolve().parents[2] / "emails").glob("*.eml"))
pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")
# a plain item, a 17-component build-your-own with the price on a component, a swipe order
SAMPLES = [p for p in EMAILS if p.name.split()[0] in ("#123709609", "#125089644", "#124452933")]


def original(p):
    msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    return msg, msg.get_body(("html",)).get_content()


def forward_html(p, prefix="FW:"):
    """Outlook-style: note + forward header + original markup + a signature table."""
    msg, body = original(p)
    inner = body.split("<body>", 1)[-1].rsplit("</body>", 1)[0] if "<body>" in body else body
    html = (f"<html><body><div>FYI, lunch today</div>"
            f"<table><tr><td>Sent from Outlook</td></tr></table><hr>"
            f"<div><b>From:</b> {msg['From']}<br><b>Sent:</b> {msg['Date']}<br>"
            f"<b>Subject:</b> {msg['Subject']}</div>{inner}"
            f"<table><tr><td>William | Duke 2028</td></tr><tr><td>Subtotal</td><td>$99.99</td></tr></table>"
            f"</body></html>")
    fwd = EmailMessage(policy=policy.default)
    fwd["Subject"] = f"{prefix} {msg['Subject']}"
    fwd["From"] = "student@example.edu"
    fwd.set_content("FYI, lunch today")
    fwd.add_alternative(html, subtype="html")
    return fwd.as_bytes()


def forward_text(p):
    """Text-only client: original text/plain (Transact puts HTML markup in it), '> '-quoted
    and re-wrapped at 76 columns, which splits tags across lines."""
    msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    plain = msg.get_body(("plain",)).get_content()
    quoted = "\n".join("> " + line for line in textwrap.wrap(plain, 76, drop_whitespace=False,
                                                              replace_whitespace=False))
    fwd = EmailMessage(policy=policy.default)
    fwd["Subject"] = f"Fwd: {msg['Subject']}"
    fwd["From"] = "student@example.edu"
    fwd.set_content(f"see below\n\n> -----Original Message-----\n> Subject: {msg['Subject']}\n>\n{quoted}\n")
    return fwd.as_bytes()


def forward_attached(paths, prefix="FW:"):
    fwd = EmailMessage(policy=policy.default)
    fwd["Subject"] = f"{prefix} receipts"
    fwd["From"] = "student@example.edu"
    fwd.set_content("attached")
    for p in paths:
        fwd.add_attachment(email.message_from_bytes(p.read_bytes(), policy=policy.default))
    return fwd.as_bytes()


def direct(p):
    [(r, _)] = parse_eml_bytes(p.read_bytes())
    return r


@pytest.mark.parametrize("p", SAMPLES, ids=lambda p: p.name.split()[0])
@pytest.mark.parametrize("prefix", ["FW:", "Fwd:", "Fwd: RE:"])
def test_html_inline_forward(p, prefix):
    [(r, _)] = parse_eml_bytes(forward_html(p, prefix))
    assert r == direct(p)  # the signature's "Subtotal $99.99" row is ignored


@pytest.mark.parametrize("p", SAMPLES, ids=lambda p: p.name.split()[0])
def test_plain_text_quoted_forward(p):
    [(r, _)] = parse_eml_bytes(forward_text(p))
    assert r == direct(p)


def test_attachment_forward_with_fw_subject():
    got = parse_eml_bytes(forward_attached(SAMPLES))
    assert [r for r, _ in got] == [direct(p) for p in SAMPLES]


def test_all_31_survive_outlook_forward():
    for p in EMAILS:
        [(r, _)] = parse_eml_bytes(forward_html(p))
        assert r == direct(p), p.name


def test_forward_without_receipt_is_rejected():
    m = EmailMessage()
    m["Subject"] = "FW: #123 Receipt"
    m.set_content("oops, forgot to include it")
    with pytest.raises(NotAReceipt):
        parse_eml_bytes(m.as_bytes())
