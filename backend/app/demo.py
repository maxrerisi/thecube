"""POST /admin/reset-demo (SPEC 14): rebuild Blue Devil, the app's only account.

The real receipts in emails/ are read as a price list (Blue Devil's meals cost what they
really cost) and the orders they create are dropped again, so Blue Devil's log holds only
its generated history plus anything forwarded since.

Removes everything a live demo adds (manual logs, forwarded receipts, typed prices, auto-
written aliases, toggled settings, entered balances) so the next run starts identical.
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from app import settings_store
from app.core import clock
from app.ingest.importer import import_emls
from app.seed import BLUE_DEVIL, EMAILS, seed_users, seed_vendors


def _user(conn, name):
    return conn.execute("SELECT id FROM users WHERE name = %s", (name,)).fetchone()["id"]


def reset(conn, emails_dir: Path = EMAILS, import_emails: bool = True) -> dict:
    from seed import blue_devil  # backend/seed/blue_devil.py
    seed_users(conn)
    devil_id = _user(conn, "Blue Devil")
    conn.execute("DELETE FROM orders WHERE user_id = %s", (devil_id,))
    conn.execute("DELETE FROM balance_snapshots WHERE user_id = %s", (devil_id,))
    # Receipt prices stay (a server without emails/ can't re-derive them); typed ones go.
    conn.execute("DELETE FROM prices WHERE source = 'manual'")
    conn.execute("TRUNCATE item_aliases, vendor_aliases")
    warnings = seed_vendors(conn)
    files = [p.read_bytes() for p in sorted(emails_dir.glob("*.eml"))] if import_emails else []
    learned = prices_from_receipts(conn, devil_id, files)
    settings_store.save(conn, devil_id, BLUE_DEVIL)
    built = blue_devil.build(conn, devil_id, clock.today(), BLUE_DEVIL.semester_end)
    return {"price_receipts": learned, "blue_devil": built, "warnings": warnings, "fingerprint": fingerprint(conn)}


def prices_from_receipts(conn, user_id: int, files: list[bytes]) -> int:
    """Import receipts only for what they teach (prices, auto aliases), then drop the orders."""
    if not files:
        return 0
    n = import_emls(conn, user_id, files)["imported"]
    conn.execute("DELETE FROM orders WHERE user_id = %s AND source = 'email'", (user_id,))
    return n


def fingerprint(conn) -> str:
    """Hash of all demo-relevant rows without serial ids: equal hashes = identical state."""
    rows = conn.execute(
        """SELECT u.name, o.ts, o.vendor_raw, o.points_spent, o.swipes_used, o.swipe_value, o.total, o.source,
                  o.external_ref, o.macros_partial,
                  (SELECT json_agg(json_build_array(oi.name, oi.price, oi.format,
                       (SELECT json_agg(json_build_array(c.raw_name, c.item_oid, c.uofm_oid, c.servings)
                                        ORDER BY c.raw_name, c.item_oid) FROM order_components c
                        WHERE c.order_item_id = oi.id)) ORDER BY oi.name, oi.price) FROM order_items oi
                   WHERE oi.order_id = o.id) AS items
           FROM orders o JOIN users u ON u.id = o.user_id ORDER BY u.name, o.ts, o.external_ref""").fetchall()
    snaps = conn.execute("""SELECT u.name, s.ts, s.points, s.swipes FROM balance_snapshots s JOIN users u ON
                            u.id = s.user_id ORDER BY 1, 2""").fetchall()
    settings = conn.execute("SELECT name, settings FROM users ORDER BY name").fetchall()
    prices = conn.execute("""SELECT v.name, item_name, variant, price, source FROM prices p JOIN vendors v
                             ON v.id = p.vendor_id ORDER BY 1, 2, 3""").fetchall()
    blob = json.dumps([rows, snaps, settings, prices], default=str, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
