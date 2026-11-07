"""Receipt import pipeline (SPEC 6 "Pipeline after parsing", steps 1-7)."""
from app.ingest import matcher
from app.ingest.receipt_parser import parse_eml_bytes
from app.schemas import ParsedReceipt


def _import_one(conn, user_id: int, rec: ParsedReceipt, raw: bytes, result: dict) -> None:
    # 1. dedup on (user_id, external_ref)
    if conn.execute("SELECT 1 FROM orders WHERE user_id = %s AND external_ref = %s",
                    (user_id, rec.order_number)).fetchone():
        result["duplicates"] += 1
        return
    with conn.transaction():
        # 2. vendor
        vendor = matcher.resolve_vendor(conn, rec.vendor_raw)
        vendor_id = vendor["id"] if vendor else None
        order = conn.execute(
            """INSERT INTO orders (user_id, ts, vendor_id, vendor_raw, subtotal, tax, total, points_spent,
                                   swipes_used, swipe_value, source, external_ref, raw_email)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'email', %s, %s)
               ON CONFLICT (user_id, external_ref) DO NOTHING RETURNING id""",
            (user_id, rec.placed_at, vendor_id, rec.vendor_raw, rec.subtotal, rec.tax, rec.total,
             rec.points_spent, rec.swipes_used, rec.swipe_value, rec.order_number, raw)).fetchone()
        if order is None:  # lost a race with a concurrent import of the same receipt
            result["duplicates"] += 1
            return
        partial = vendor is None or vendor["unit_oid"] is None
        for it in rec.items:
            # 3. prices: keep the latest observation per (vendor, item, variant)
            if vendor_id is not None:
                conn.execute(
                    """INSERT INTO prices (vendor_id, item_name, variant, price, source, observed_at)
                       VALUES (%s, %s, %s, %s, 'receipt', %s)
                       ON CONFLICT (vendor_id, item_name, variant) DO UPDATE
                         SET price = EXCLUDED.price, source = EXCLUDED.source, observed_at = EXCLUDED.observed_at
                         WHERE prices.observed_at <= EXCLUDED.observed_at""",
                    (vendor_id, it.name, it.priced_component or "", it.price, rec.placed_at))
            # 4. format
            fmt = matcher.item_format(it.name)
            item_id = conn.execute(
                "INSERT INTO order_items (order_id, name, price, format) VALUES (%s, %s, %s, %s) RETURNING id",
                (order["id"], it.name, it.price, fmt)).fetchone()["id"]
            # 5. components -> item_oid; an item with no components is its own single component
            for raw_name in it.components or [it.name]:
                oid = matcher.match_component(conn, vendor, raw_name, fmt)
                uofm = matcher.pick_portion(conn, oid, fmt) if oid else None
                conn.execute(
                    """INSERT INTO order_components (order_item_id, raw_name, item_oid, uofm_oid, servings)
                       VALUES (%s, %s, %s, %s, 1)""", (item_id, raw_name, oid, uofm))
                if oid is None:
                    partial = True
                    unk = {"vendor": rec.vendor_raw, "name": raw_name}
                    if unk not in result["unknown_components"]:
                        result["unknown_components"].append(unk)
        # 6. macros_partial
        conn.execute("UPDATE orders SET macros_partial = %s WHERE id = %s", (partial, order["id"]))
    result["imported"] += 1
    if partial:
        result["partial"].append(rec.order_number)


def import_emls(conn, user_id: int, files: list[bytes]) -> dict:
    """Parse every file first (all-or-nothing on bad input), then import. 7. returns the summary."""
    receipts = [pair for raw in files for pair in parse_eml_bytes(raw)]
    result = {"imported": 0, "duplicates": 0, "partial": [], "unknown_components": []}
    for rec, raw in receipts:
        _import_one(conn, user_id, rec, raw, result)
    return result
