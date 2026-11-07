"""Jordan: the fake demo user (SPEC 14). Deterministic (random.seed(42)) given "today".

28 days of orders built from REAL NetNutrition items and REAL receipt prices (from
William's receipts). Story: goal build_muscle (2,800 cal / 150 g protein), short on protein
most weekdays, on pace to run out of points ~6 days early. Today: breakfast + lunch logged,
~70 g protein. No restrictions at start (the demo toggles Halal + Peanut live).
"""
import random
from datetime import date, datetime, time, timedelta

from app.core.clock import NY
from app.ingest.matcher import item_format

DAYS = 28
RUNOUT_EARLY_DAYS = 6
START_SWIPES = 14
SWIPE_VALUE = 11.80  # Board Plan Equivalency seen on William's receipts
TAX = 0.075

# Meal templates: (vendor, receipt item name, receipt variant -> price from `prices`,
#                  [(NetNutrition item, course substring, portion keyword or None)])
MEALS = {
    # breakfasts (Skillet / Trinity)
    "biscuit":   ("The Skillet", "Biscuit Egg Cheese with Protein", "",
                  [("Biscuit", "Build a Biscuit", None), ("Cooked Eggs", "Build a Biscuit", None),
                   ("Cheddar Cheese Slice", "", None), ("Bacon", "", None)]),
    "yogurt":    ("The Skillet", "Vanilla Greek Yogurt Cup", "", [("Greek Vanilla Yogurt", "", None)]),
    "pancakes":  ("The Skillet", "Pancake Breakfast", "Full Stack", [("Pancakes", "", "4")]),
    "latte":     ("Trinity Cafe", "Latte", "Iced Latte", [("Iced Latte Whole Milk", "", None)]),
    # lunches / dinners
    "burrito":   ("Sazon", "Burrito", "Grilled Chicken",
                  [('Flour Tortilla 12"', "", "burrito"), ("Cilantro Lime White Rice", "", "burrito"),
                   ("Chipotle Chicken", "", "burrito"), ("Black Beans", "", "burrito"),
                   ("Pico de Gallo", "Topping", "burrito"), ("Fajita Peppers and Onions", "", "burrito")]),
    "arepa":     ("Sazon", "Arepa Bowl", "Hot Honey Chicken",
                  [("Latin Arepa Bowl", "Topping", None), ("Cilantro Lime White Rice", "", "arepa"),
                   ("Hot Honey Chicken", "", "arepa"), ("Black Beans", "", "arepa"), ("Corn Salsa", "", "arepa")]),
    "quesadilla": ("Sazon", "Quesadilla", "Hot Honey Chicken",
                   [('Flour Tortilla 12"', "", "tortilla"), ("Hot Honey Chicken", "", "quesadilla"),
                    ("Shredded Cheddar Monterey Jack Cheese", "", "quesadilla"), ("Pico de Gallo", "Topping", "quesadilla")]),
    "sazon5":    ("Sazon", "$5 Meal Deal", "", [("Chipotle Chicken", "", None), ("Chips and Salsa", "", None)]),
    "tokyo":     ("Ginger + Soy", "Tokyo (Teriyaki Chicken)", "",
                  [("Grilled Teriyaki Chicken", "Tokyo", None), ("White Rice", "", None),
                   ("Seasoned Broccoli", "Make Your Own", None), ("Teriyaki Sauce", "", None)]),
    "poke":      ("Ginger + Soy", "Salmon Poke Bowl", "",
                  [("Marinated Salmon", "", None), ("White Rice", "", None), ("Spicy Mayo", "", None),
                   ("Kimchi Slaw", "", None)]),
    "sashimi":   ("Gyotaku", "Sashimi Bowl", "",
                  [("Salmon", "Sashimi Bowl (Fish", None), ("Sushi Rice", "Sashimi Bowl (Base", None),
                   ("Shelled Edamame", "", None), ("Cucumber", "", None), ("Spicy Mayo", "", None)]),
    "thyme":     ("It's Thyme", "Build Your Own Bowl", "",
                  [("Brown Rice and Quinoa", "", None), ("Caribbean Jerk Chicken", "", None),
                   ("Cucumbers", "", None), ("Red Pickled Onion", "", None), ("Cilantro Lime Vinaigrette", "", None)]),
    "tandoor":   ("Tandoor", "Monday Non-Vegetarian Combo", "",
                  [("Chicken Tikka Masala", "", None), ("Chicken Curry", "", None), ("Basmati Rice Pilaf", "", None)]),
    "farmstead5": ("The Farmstead", "$5 Meal Deal", "", [("Tangy Bourbon Chicken", "", None)]),
}
WEEKDAY_BREAKFAST = ["latte", "yogurt", "latte", "biscuit"]          # light, low protein
WEEKDAY_LUNCH = ["sazon5", "thyme", "farmstead5", "quesadilla", "sazon5", "poke"]
WEEKDAY_DINNER = ["quesadilla", "arepa", "poke", "sashimi", "burrito", "tandoor"]
# (slot, meal); slot 0 breakfast, 1 lunch, 2 afternoon, 3 dinner. The 4-meal day hits 150 g.
WEEKEND_MEALS = [[(0, "pancakes"), (1, "burrito"), (3, "tokyo")],
                 [(0, "biscuit"), (1, "arepa"), (3, "sashimi")],
                 [(0, "biscuit"), (1, "quesadilla"), (2, "farmstead5"), (3, "tokyo")]]
TODAY_MEALS = ["biscuit", "tokyo"]   # breakfast + lunch already logged today
SWIPE_MEALS = {"thyme"}              # It's Thyme lunches use a meal swipe, like William's
TIMES = {0: (8, 30), 1: (12, 5), 2: (15, 30), 3: (18, 30)}  # base local time per slot (+-20..40 min)


def _component(conn, unit_oid, name, course, word):
    item = conn.execute(
        """SELECT item_oid FROM nn_items WHERE unit_oid = %s AND name = %s AND course LIKE %s
           ORDER BY menu_date DESC NULLS LAST, item_oid LIMIT 1""", (unit_oid, name, f"%{course}%")).fetchone()
    if not item:
        raise LookupError(f"Jordan seed: {name!r} ({course!r}) not on unit {unit_oid}'s menu")
    ps = conn.execute("SELECT uofm_oid, portion_name, is_default FROM nn_portions WHERE item_oid = %s ORDER BY uofm_oid",
                      (item["item_oid"],)).fetchall()
    hit = next((p for p in ps if word and word in p["portion_name"].lower().split()), None) if word else None
    hit = hit or next(p for p in ps if p["is_default"])
    return item["item_oid"], hit["uofm_oid"]


def resolve_meals(conn) -> dict:
    """-> {key: {vendor_id, vendor, item, variant, price, components: [(name, item_oid, uofm_oid)]}}"""
    out = {}
    for key, (vname, item, variant, comps) in MEALS.items():
        v = conn.execute("SELECT id, unit_oid FROM vendors WHERE name = %s", (vname,)).fetchone()
        price = conn.execute("""SELECT price FROM prices WHERE vendor_id = %s AND item_name = %s AND variant = %s""",
                             (v["id"], item, variant)).fetchone()
        if not price:
            raise LookupError(f"Jordan seed: no receipt price for {vname} / {item} / {variant!r}; import William first")
        out[key] = {"vendor_id": v["id"], "vendor": vname, "item": item, "variant": variant,
                    "price": float(price["price"]),
                    "components": [(n, *_component(conn, v["unit_oid"], n, c, w)) for n, c, w in comps]}
    return out


def plan(today: date) -> list[tuple[datetime, str]]:
    """Deterministic schedule: [(local datetime, meal key)] for the 28 days before today + today."""
    rng = random.Random(42)
    out = []
    for back in range(DAYS, 0, -1):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            day = rng.choice(WEEKEND_MEALS)
        else:
            day = [(0, rng.choice(WEEKDAY_BREAKFAST)), (1, rng.choice(WEEKDAY_LUNCH)), (3, rng.choice(WEEKDAY_DINNER))]
            if rng.random() < 0.25:
                day = day[1:]  # skipped breakfast
        for slot, key in day:
            h, m = TIMES[slot]
            out.append((datetime.combine(d, time(h, m), NY) + timedelta(minutes=rng.randint(-20, 40)), key))
    for slot, key in enumerate(TODAY_MEALS):
        h, m = TIMES[slot]
        out.append((datetime.combine(today, time(h, m), NY), key))
    return out


def build(conn, user_id: int, today: date, semester_end: date) -> dict:
    """Delete and rebuild Jordan's orders + balance snapshot. Returns a summary."""
    conn.execute("DELETE FROM orders WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM balance_snapshots WHERE user_id = %s", (user_id,))
    meals = resolve_meals(conn)
    schedule = plan(today)
    spends = []
    for i, (ts, key) in enumerate(schedule):
        m = meals[key]
        swipe = key in SWIPE_MEALS
        points_base = max(m["price"] - SWIPE_VALUE, 0) if swipe else m["price"]
        tax = round(points_base * TAX, 2)
        points = round(points_base + tax, 2)
        oid = conn.execute(
            """INSERT INTO orders (user_id, ts, vendor_id, vendor_raw, subtotal, tax, total, points_spent,
                                   swipes_used, swipe_value, source, external_ref, macros_partial)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'seed', %s, false) RETURNING id""",
            (user_id, ts, m["vendor_id"], m["vendor"], m["price"], tax, round(m["price"] + tax, 2), points,
             1 if swipe else 0, SWIPE_VALUE if swipe else 0, f"jordan-{ts:%Y%m%d-%H%M}-{i}")).fetchone()["id"]
        oi = conn.execute("INSERT INTO order_items (order_id, name, price, format) VALUES (%s, %s, %s, %s) RETURNING id",
                          (oid, m["item"], m["price"], item_format(m["item"]))).fetchone()["id"]
        for name, item_oid, uofm in m["components"]:
            conn.execute("""INSERT INTO order_components (order_item_id, raw_name, item_oid, uofm_oid, servings)
                            VALUES (%s, %s, %s, %s, 1)""", (oi, name, item_oid, uofm))
        spends.append((ts, points, 1 if swipe else 0))
    # Balance snapshot at the start, sized so the trailing-7-day pace runs out RUNOUT_EARLY_DAYS early.
    week = [p for ts, p, _ in spends if today - timedelta(days=7) <= ts.date() < today]
    trailing = sum(week) / 7
    days_left = max((semester_end - today).days, 1)
    target_now = round(trailing * (days_left - RUNOUT_EARLY_DAYS) + trailing / 2, 2)  # mid-day: floor() lands on -6
    snap_ts = datetime.combine(today - timedelta(days=DAYS), time(6, 0), NY)
    spent_since = sum(p for _, p, _ in spends)
    swipes_since = sum(s for _, _, s in spends)
    conn.execute("INSERT INTO balance_snapshots (user_id, ts, points, swipes) VALUES (%s, %s, %s, %s)",
                 (user_id, snap_ts, round(target_now + spent_since, 2), START_SWIPES + swipes_since))
    return {"orders": len(schedule), "points_now": target_now, "trailing_daily": round(trailing, 2)}
