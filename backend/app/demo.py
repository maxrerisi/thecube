"""POST /admin/reset-demo (SPEC 14): rebuild Jordan; re-import William from emails/.

Removes everything a live demo adds (manual logs, forwarded receipts, typed prices, auto-
written aliases, toggled settings, entered balances) so the next run starts identical.
William's real balance is "entered by hand" once in the env var WILLIAM_BALANCE
("points,swipes,2026-11-07T09:00-05:00"); every reset restores exactly that snapshot.
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from app import settings_store
from app.core import clock
from app.ingest.importer import import_emls
from app.seed import EMAILS, JORDAN, seed_users, seed_vendors


def william_balance() -> tuple[float, int | None, datetime] | None:
    raw = os.environ.get("WILLIAM_BALANCE")
    if not raw:
        return None
    pts, swipes, ts = (x.strip() for x in raw.split(","))
    return float(pts), int(swipes) if swipes else None, datetime.fromisoformat(ts)


def _user(conn, name):
    return conn.execute("SELECT id FROM users WHERE name = %s", (name,)).fetchone()["id"]


def reset(conn, emails_dir: Path = EMAILS) -> dict:
    from seed import jordan  # backend/seed/jordan.py
    seed_users(conn)
    william, jordan_id = _user(conn, "William"), _user(conn, "Jordan")
    conn.execute("DELETE FROM orders WHERE user_id = ANY(%s)", ([william, jordan_id],))
    conn.execute("DELETE FROM balance_snapshots WHERE user_id = %s", (william,))
    if base := william_balance():
        conn.execute("INSERT INTO balance_snapshots (user_id, ts, points, swipes) VALUES (%s, %s, %s, %s)",
                     (william, base[2], base[0], base[1]))
    conn.execute("TRUNCATE prices, item_aliases, vendor_aliases")
    warnings = seed_vendors(conn)
    files = [p.read_bytes() for p in sorted(emails_dir.glob("*.eml"))]
    imported = import_emls(conn, william, files) if files else {"imported": 0}
    settings_store.save(conn, jordan_id, JORDAN)
    built = jordan.build(conn, jordan_id, clock.today(), JORDAN.semester_end)
    return {"william": {"imported": imported["imported"], "partial": len(imported.get("partial", []))},
            "jordan": built, "warnings": warnings, "fingerprint": fingerprint(conn)}


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
