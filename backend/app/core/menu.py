"""A vendor's current NetNutrition menu with portions, traits and known prices."""
from collections import defaultdict


def current_items(conn, unit_oid: int) -> list[dict]:
    """Items on the unit's latest menu (retail: menu_date NULL; dated menus: the newest date),
    each with its portions. Ordered by course as NetNutrition lists them (item_oid order)."""
    items = conn.execute(
        """SELECT item_oid, course, name, allergens, diets, ingredients, menu_date, meal FROM nn_items
           WHERE unit_oid = %s AND menu_date IS NOT DISTINCT FROM
                 (SELECT max(menu_date) FROM nn_items WHERE unit_oid = %s)
           ORDER BY item_oid""", (unit_oid, unit_oid)).fetchall()
    portions = defaultdict(list)
    for p in conn.execute(
            """SELECT item_oid, uofm_oid, portion_name, is_default, grams, calories, protein_g, carbs_g, fat_g,
                      fiber_g, sugar_g, sodium_mg FROM nn_portions WHERE item_oid = ANY(%s)
               ORDER BY item_oid, NOT is_default, uofm_oid""", ([i["item_oid"] for i in items],)).fetchall():
        portions[p["item_oid"]].append(p)
    for i in items:
        i["portions"] = portions[i["item_oid"]]
    return items


def known_prices(conn, vendor_id: int) -> tuple[dict[int, dict], dict[str, dict]]:
    """-> (by item_oid, by lowercased name) of {price, label, source}.

    A receipt price is keyed by its item name and, for build-your-own, its priced component
    ("Arepa Bowl" / "Hot Honey Chicken" -> 12.85 shows on Hot Honey Chicken as
    "Arepa Bowl with Hot Honey Chicken"). item_aliases carry receipt names over to item_oids."""
    by_name: dict[str, dict] = {}
    for r in conn.execute("""SELECT item_name, variant, price, source FROM prices WHERE vendor_id = %s
                             ORDER BY observed_at""", (vendor_id,)).fetchall():
        price = {"price": float(r["price"]), "source": r["source"],
                 "label": f"{r['item_name']} with {r['variant']}" if r["variant"] else r["item_name"]}
        by_name[r["item_name"].lower()] = price if not r["variant"] else by_name.get(r["item_name"].lower(), price)
        if r["variant"]:
            by_name[r["variant"].lower()] = price
    by_oid = {}
    for a in conn.execute("SELECT raw, item_oid FROM item_aliases WHERE vendor_id = %s", (vendor_id,)).fetchall():
        if a["raw"] in by_name:
            by_oid[a["item_oid"]] = by_name[a["raw"]]
    return by_oid, by_name


def price_for(item: dict, by_oid: dict, by_name: dict) -> dict | None:
    return by_oid.get(item["item_oid"]) or by_name.get(item["name"].lower())
