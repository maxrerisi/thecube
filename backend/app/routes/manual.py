"""Manual log (SPEC 7): POST /orders/manual, DELETE /orders/{id}."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_token
from app.core import clock, macros, menu
from app.db import get_conn
from app.routes.menu import vendor_row

router = APIRouter(dependencies=[Depends(require_token)])
TAX = 0.075


class ManualItem(BaseModel):
    item_oid: int
    uofm_oid: int
    servings: float = Field(default=1, gt=0)
    price: float | None = Field(default=None, ge=0)  # SPEC 7: typed when no known price


class ManualOrder(BaseModel):
    user_id: int
    vendor_id: int
    ts: datetime | None = None          # default: now
    items: list[ManualItem] = Field(min_length=1)
    points_spent: float | None = Field(default=None, ge=0)  # default: sum(prices) x 1.075
    swipes_used: int = Field(default=0, ge=0)


@router.post("/orders/manual")
def create_manual(o: ManualOrder, conn=Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM users WHERE id = %s", (o.user_id,)).fetchone():
        raise HTTPException(404, f"no user {o.user_id}")
    v = vendor_row(conn, o.vendor_id)
    ts = o.ts or clock.now()
    by_oid, by_name = menu.known_prices(conn, o.vendor_id)
    lines = []
    for it in o.items:
        row = conn.execute("""SELECT i.item_oid, i.name, i.unit_oid FROM nn_items i JOIN nn_portions p USING (item_oid)
                              WHERE i.item_oid = %s AND p.uofm_oid = %s""", (it.item_oid, it.uofm_oid)).fetchone()
        if not row or row["unit_oid"] != v["unit_oid"]:
            raise HTTPException(422, f"item {it.item_oid}/{it.uofm_oid} is not on {v['name']}'s menu")
        known = menu.price_for(row, by_oid, by_name)
        unit_price = it.price if it.price is not None else (known["price"] if known else None)
        if it.price is not None:  # SPEC 7: typed prices are remembered
            conn.execute(
                """INSERT INTO prices (vendor_id, item_name, variant, price, source, observed_at)
                   VALUES (%s, %s, '', %s, 'manual', %s)
                   ON CONFLICT (vendor_id, item_name, variant) DO UPDATE SET price = EXCLUDED.price,
                     source = EXCLUDED.source, observed_at = EXCLUDED.observed_at""",
                (o.vendor_id, row["name"], it.price, ts))
        lines.append((it, row["name"], None if unit_price is None else round(unit_price * it.servings, 2)))
    priced = [p for _, _, p in lines if p is not None]
    subtotal = round(sum(priced), 2) if priced else None
    points = o.points_spent if o.points_spent is not None else round((subtotal or 0) * (1 + TAX), 2)
    order_id = conn.execute(
        """INSERT INTO orders (user_id, ts, vendor_id, vendor_raw, subtotal, tax, total, points_spent,
                               swipes_used, source, macros_partial)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual', false) RETURNING id""",
        (o.user_id, ts, o.vendor_id, v["name"], subtotal,
         round(subtotal * TAX, 2) if subtotal is not None else None,
         round(subtotal * (1 + TAX), 2) if subtotal is not None else None, points, o.swipes_used)).fetchone()["id"]
    for it, name, price in lines:
        oi = conn.execute("INSERT INTO order_items (order_id, name, price) VALUES (%s, %s, %s) RETURNING id",
                          (order_id, name, price)).fetchone()["id"]
        conn.execute("""INSERT INTO order_components (order_item_id, raw_name, item_oid, uofm_oid, servings)
                        VALUES (%s, %s, %s, %s, %s)""", (oi, name, it.item_oid, it.uofm_oid, it.servings))
    return {"id": order_id, "ts": ts.isoformat(), "vendor": v["name"], "subtotal": subtotal,
            "points_spent": points, "swipes_used": o.swipes_used,
            "macros": macros.order_macros(conn, [order_id])[order_id]}


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, user_id: int, conn=Depends(get_conn)):
    gone = conn.execute("DELETE FROM orders WHERE id = %s AND user_id = %s RETURNING id",
                        (order_id, user_id)).fetchone()
    if not gone:
        raise HTTPException(404, f"no order {order_id} for user {user_id}")
    return {"deleted": order_id}
