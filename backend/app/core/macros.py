"""Macros for orders: sum of matched components' portion macros x servings."""
KEYS = ("calories", "protein_g", "carbs_g", "fat_g")


def order_macros(conn, order_ids: list[int]) -> dict[int, dict]:
    """-> {order_id: {calories, protein_g, carbs_g, fat_g}} (unmatched components count 0)."""
    out = {oid: dict.fromkeys(KEYS, 0.0) for oid in order_ids}
    if not order_ids:
        return out
    rows = conn.execute(
        """SELECT oi.order_id, sum(p.calories * c.servings) AS calories, sum(p.protein_g * c.servings) AS protein_g,
                  sum(p.carbs_g * c.servings) AS carbs_g, sum(p.fat_g * c.servings) AS fat_g
           FROM order_items oi JOIN order_components c ON c.order_item_id = oi.id
           JOIN nn_portions p ON p.item_oid = c.item_oid AND p.uofm_oid = c.uofm_oid
           WHERE oi.order_id = ANY(%s) GROUP BY oi.order_id""", (order_ids,)).fetchall()
    for r in rows:
        out[r["order_id"]] = {k: round(float(r[k] or 0), 1) for k in KEYS}
    return out


def total(per_order: dict[int, dict]) -> dict:
    return {k: round(sum(m[k] for m in per_order.values()), 1) for k in KEYS}
