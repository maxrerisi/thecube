"""Postmark inbound webhook payload -> .eml bytes for the normal receipt pipeline (SPEC 6).

Postmark sends JSON: From/FromFull, Subject, HtmlBody, TextBody, Attachments [{Name, Content
(base64), ContentType}]. A forwarded receipt is either inline in HtmlBody/TextBody (Outlook
"Forward") or an attached .eml ("Forward as attachment"); parse_eml_bytes handles both.
"""
import base64
import email
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr


def sender(payload: dict) -> str:
    full = payload.get("FromFull") or {}
    return (full.get("Email") or parseaddr(payload.get("From", ""))[1] or "").strip().lower()


def to_eml(payload: dict) -> bytes:
    msg = EmailMessage(policy=policy.default)
    msg["Subject"] = payload.get("Subject", "")
    msg["From"] = payload.get("From", "")
    msg.set_content(payload.get("TextBody") or "(no text body)")
    if payload.get("HtmlBody"):
        msg.add_alternative(payload["HtmlBody"], subtype="html")
    for a in payload.get("Attachments") or []:
        data = base64.b64decode(a.get("Content", ""))
        name = a.get("Name") or "attachment"
        ctype = (a.get("ContentType") or "application/octet-stream").lower()
        if ctype == "message/rfc822" or name.lower().endswith(".eml"):
            msg.add_attachment(email.message_from_bytes(data, policy=policy.default))
        else:
            maintype, _, subtype = ctype.partition("/")
            msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    return msg.as_bytes()
