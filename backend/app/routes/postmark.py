"""POST /ingest/postmark (SPEC 6, 12): Postmark inbound, HTTP basic auth from env."""
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.db import get_conn
from app.ingest import postmark
from app.ingest.importer import import_emls

router = APIRouter()
basic = HTTPBasic(auto_error=False)
log = logging.getLogger("postmark")


def require_basic(creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
    user, pw = os.environ.get("POSTMARK_WEBHOOK_USER"), os.environ.get("POSTMARK_WEBHOOK_PASS")
    if not user or not pw:
        raise HTTPException(500, "POSTMARK_WEBHOOK_USER/PASS not set on the server")
    ok = creds is not None and hmac.compare_digest(creds.username.encode(), user.encode()) \
        and hmac.compare_digest(creds.password.encode(), pw.encode())
    if not ok:
        raise HTTPException(401, "bad credentials", headers={"WWW-Authenticate": "Basic"})


@router.post("/ingest/postmark", dependencies=[Depends(require_basic)])
async def ingest_postmark(request: Request, conn=Depends(get_conn)):
    """Always 200 for well-formed requests we can't use (unknown sender, not a receipt) so
    Postmark doesn't retry them; the reason is in the body and the log."""
    payload = await request.json()
    who = postmark.sender(payload)
    # One-user app: a known sender address picks its user; anything else goes to the demo
    # student (Blue Devil), e.g. Outlook sending from an alias (william.z@) rather than the
    # NetID address the receipts were sent to (wz231@). The webhook itself needs basic auth.
    user = conn.execute("SELECT id FROM users WHERE lower(email) = %s", (who,)).fetchone() \
        or conn.execute("SELECT id FROM users WHERE is_demo ORDER BY id LIMIT 1").fetchone()
    if not user:
        log.warning("postmark: no user for sender %r", who)
        return {"status": "ignored", "reason": "unknown sender"}
    try:
        result = import_emls(conn, user["id"], [postmark.to_eml(payload)])
    except ValueError as e:  # NotAReceipt or unparseable
        log.warning("postmark: %s", e)
        return {"status": "ignored", "reason": str(e)}
    log.info("postmark: user %s %s", user["id"], result)
    return {"status": "ok", "user_id": user["id"], **result}
