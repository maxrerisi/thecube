"""Next-meal optimizer (SPEC 10). Code computes every number; the coach only words them.

Candidates are priced meals at vendors with NetNutrition data:
- simple items: a `prices` row whose item (or alias) is an nn item at that unit;
- build-your-own templates (seed/templates.json), combos generated from the current menu.

Diet rule (interpretation, see SPEC 10 note): every component must carry the required diet;
Vegan counts as Vegetarian and as Halal (NetNutrition tags Halal only on meats). Items with no
trait data at all are excluded whenever any restriction is set.
Additions to SPEC 10: a candidate must cover >= 30% of the per-meal calorie target; under
bias "protein" only falling short of the protein target is penalized (more is fine).
"""
import json
from itertools import product
from pathlib import Path

from app import settings_store
from app.core import budget, clock, hours, macros, menu
from app.ingest.matcher import FORMAT_WORD

TEMPLATES = Path(__file__).resolve().parents[2] / "seed" / "templates.json"
TAX = 0.075
CAP_PER_VENDOR = 200
MIN_MEAL_PROTEIN, MIN_MEAL_CAL = 20.0, 400.0  # scoring floor when today's targets are already met
MIN_MEAL_SHARE = 0.3       # a pick must cover >= 30% of the per-meal calorie target (no yogurt-cup "meals")
MAX_COMPONENT_CAL = 1500  # skip "Batch"-sized labels (It's Thyme White Rice: 8,500 cal)
MACRO_KEYS = ("calories", "protein_g", "carbs_g", "fat_g")
BIAS_FROM_GOAL = {"build_muscle": "protein", "budget": "cheap", "balanced": "balanced"}


# ---------- traits ----------

def allowed(item: dict, require_diets: list[str], avoid_allergens: list[str]) -> bool:
    if not require_diets and not avoid_allergens:
        return True
    if not item["diets"] and not item["allergens"]:
        return False  # no trait data
    if any(a in item["allergens"] for a in avoid_allergens):
        return False
    diets = set(item["diets"])
    if "vegan" in diets:
        diets |= {"vegetarian", "halal"}
    return all(d in diets for d in require_diets)


# ---------- portions / components ----------

def portion(item: dict, word: str | None) -> dict | None:
    ps = [p for p in item["portions"] if (p["calories"] or 0) <= MAX_COMPONENT_CAL]
    if not ps:
        return None
    hit = next((p for p in ps if word and word in p["portion_name"].lower().split()), None)
    return hit or next((p for p in ps if p["is_default"]), ps[0])


def component(item: dict, word: str | None) -> dict | None:
    p = portion(item, word)
    if p is None:
        return None
    return {"name": item["name"], "item_oid": item["item_oid"], "uofm_oid": p["uofm_oid"], "portion": p["portion_name"],
            **{k: float(p[k] or 0) for k in MACRO_KEYS}}


def sum_macros(comps: list[dict]) -> dict:
    return {k: round(sum(c[k] for c in comps), 1) for k in MACRO_KEYS}


# ---------- candidates ----------

def _price_lookup(conn, vendor_id):
    rows = conn.execute("""SELECT item_name, variant, price FROM prices WHERE vendor_id = %s
                           ORDER BY observed_at DESC""", (vendor_id,)).fetchall()
    alias = {r["raw"]: r["name"] for r in conn.execute(
        """SELECT a.raw, i.name FROM item_aliases a JOIN nn_items i USING (item_oid) WHERE a.vendor_id = %s""",
        (vendor_id,)).fetchall()}
    return rows, alias


def template_candidates(tpl: dict, items: list[dict], rows, alias, ok) -> list[dict]:
    word = FORMAT_WORD.get(tpl.get("format"))
    def course_items(slot):
        its = [i for i in items if slot["course"] in i["course"]
               and (not slot.get("course_any") or any(c in i["course"] for c in slot["course_any"]))
               and (not slot.get("names") or i["name"] in slot["names"])
               and i["name"] not in slot.get("exclude", [])]
        return [c for i in its if ok(i) and (c := component(i, word))]
    includes = []
    for inc in tpl["include"]:
        it = next((i for i in items if i["name"] == inc["name"] and inc["course"] in i["course"]), None)
        if it is None or not ok(it):
            return []
        c = component(it, inc.get("portion") or word)
        if c is None:
            return []
        includes.append(c)
    price_rows = [r for r in rows if r["item_name"] == tpl["price_item"]]
    if not price_rows:
        return []
    def price_for(protein):
        if tpl.get("priced_by_protein") and protein:
            for r in price_rows:
                if r["variant"] and (r["variant"] == protein["name"] or alias.get(r["variant"].lower()) == protein["name"]):
                    return float(r["price"])
        return float(price_rows[0]["price"])  # most recent price for this item
    choices = []
    for slot in tpl["slots"]:
        opts = course_items(slot)
        if slot["max"] == 1:
            if slot["role"] == "sauce" and len(opts) > 2:  # lightest + richest sauce
                opts = [min(opts, key=lambda c: c["calories"]), max(opts, key=lambda c: c["calories"])]
            if not opts and slot["min"] >= 1:
                return []
            choices.append([[o] for o in opts] or [[]])
        else:  # multi-pick: a protein-heavy set and a lean set
            n = min(slot["max"], len(opts))
            hearty = sorted(opts, key=lambda c: (-c["protein_g"], c["calories"], c["name"]))[:n]
            lean = sorted(opts, key=lambda c: (c["calories"], c["name"]))[:n]
            choices.append([hearty, lean] if hearty != lean else [hearty])
    out, seen = [], set()
    for combo in product(*choices) if choices else [()]:
        comps = includes + [c for group in combo for c in group]
        key = tuple(sorted((c["item_oid"], c["uofm_oid"]) for c in comps))
        if key in seen:
            continue
        seen.add(key)
        protein = next((group[0] for slot, group in zip(tpl["slots"], combo) if slot["role"] == "protein" and group), None)
        title = tpl["name"] + (f" with {protein['name']}" if protein and not tpl.get("fixed") else "")
        out.append({"title": title, "group": tpl["name"], "kind": "template", "components": comps,
                    "price": price_for(protein)})
    return out


def simple_candidates(items, rows, alias, template_items, ok) -> list[dict]:
    by_name = {i["name"]: i for i in items}
    out, seen = [], set()
    for r in rows:
        if r["item_name"] in template_items:
            continue
        name = (alias.get(r["item_name"].lower()) or (alias.get(r["variant"].lower()) if r["variant"] else None)
                or (r["item_name"] if r["item_name"] in by_name else None))
        it = by_name.get(name)
        if not it or not ok(it) or (r["item_name"], r["variant"]) in seen:
            continue
        seen.add((r["item_name"], r["variant"]))
        c = component(it, None)
        if c:
            out.append({"title": r["item_name"], "group": r["item_name"], "kind": "item", "components": [c],
                        "price": float(r["price"])})
    return out


# ---------- scoring ----------

def score(m: dict, p_t: float, c_t: float, headroom: float | None, history_share: float, bias: str,
          ref_price: float = 12.0) -> float:
    """Higher is better. Each bias optimizes a different thing (they used to share one formula,
    and with little points headroom the price term swamped everything, so all tabs agreed):
      balanced: closest to this meal's protein + calorie targets, price a mild tiebreak;
      protein:  most protein (up to 1.5x the target), price barely matters;
      cheap:    fewest points, as long as it is a real meal (protein shortfall still costs).
    Prices are scaled by ref_price (half the daily budget, a typical meal), not by today's
    headroom, so a nearly-spent day doesn't make every option look equally terrible."""
    p_t, c_t = max(p_t, 1.0), max(c_t, 1.0)
    cost = m["points_cost"] / ref_price
    over = 0.0 if headroom is None else max(0.0, m["points_cost"] - max(headroom, 0.0)) / ref_price
    short = max(0.0, p_t - m["protein_g"]) / p_t
    extra = max(0.0, m["protein_g"] - p_t) / p_t
    cal_dev = abs(m["calories"] - c_t) / c_t
    if bias == "protein":
        s = 2.0 * min(m["protein_g"] / p_t, 1.5) - 0.3 * cal_dev - 0.15 * over - 0.1 * cost
    elif bias == "cheap":
        s = -2.0 * cost - 0.5 * over - 0.8 * short - 0.2 * cal_dev
    else:
        s = -1.2 * short - 0.6 * extra - 0.8 * cal_dev - 0.35 * over - 0.25 * cost
    return s + 0.1 * history_share


ATE_HERE_TODAY = 0.6  # variety: a place already eaten at today drops below the other good options


def pick_top(cands: list[dict], n=3) -> list[dict]:
    """Top n by score, across at least 2 vendors when possible, one per template per vendor
    (so the picks differ by more than a sausage)."""
    ranked = sorted(cands, key=lambda c: (-c["score"], c["points_cost"], c["vendor"], c["title"]))
    picks = []
    for c in ranked:
        if len(picks) == n:
            break
        if any(p["vendor_id"] == c["vendor_id"] and p["group"] == c["group"] for p in picks):
            continue
        if len(picks) == n - 1 and len({p["vendor_id"] for p in picks} | {c["vendor_id"]}) < 2 \
                and any(o["vendor_id"] != picks[0]["vendor_id"] for o in ranked):
            continue  # save the last slot for a second vendor
        picks.append(c)
    return picks


def suggest(conn, user_id: int, bias: str | None = None) -> dict:
    user, s = settings_store.load(conn, user_id)
    bias = bias or BIAS_FROM_GOAL[s.goal]
    at, today = clock.now(), clock.today()
    start, end = clock.day_bounds(today)
    ids = [r["id"] for r in conn.execute("SELECT id FROM orders WHERE user_id = %s AND ts >= %s AND ts < %s",
                                         (user_id, start, end)).fetchall()]
    eaten = macros.total(macros.order_macros(conn, ids))
    meals_left = 1 if at.hour >= 17 else 2
    p_t = max(s.targets.protein_g - eaten["protein_g"], 0) / meals_left
    c_t = max(s.targets.calories - eaten["calories"], 0) / meals_left
    # Score against at least a real meal's worth: once today's targets are met, a 0 target would
    # make sauces and sides the "best" picks. The displayed per-meal target stays the true one.
    p_s, c_s = max(p_t, MIN_MEAL_PROTEIN), max(c_t, MIN_MEAL_CAL)
    pts = budget.status(conn, user_id, s.semester_end, today, s.meal_plan)
    headroom = None if pts.daily_budget is None else pts.daily_budget - pts.spent_today
    ref_price = max((pts.daily_budget or 24.0) / 2, 8.0)  # a typical meal for this budget
    today_vendors = {r["vendor_id"] for r in conn.execute(
        "SELECT DISTINCT vendor_id FROM orders WHERE user_id = %s AND ts >= %s AND ts < %s",
        (user_id, start, end)).fetchall()}
    hist = {r["vendor_id"]: r["n"] for r in conn.execute(
        "SELECT vendor_id, count(*) AS n FROM orders WHERE user_id = %s GROUP BY vendor_id", (user_id,)).fetchall()}
    n_orders = sum(hist.values()) or 1

    vendors = conn.execute("SELECT id, name, unit_oid, hours FROM vendors WHERE unit_oid IS NOT NULL ORDER BY id").fetchall()
    from datetime import timedelta
    ok = lambda i: allowed(i, s.require_diets, s.avoid_allergens)  # noqa: E731
    templates = json.loads(TEMPLATES.read_text())["templates"]

    def candidates(vs, soon: bool) -> list[dict]:
        out = []
        for v in vs:
            items = menu.current_items(conn, v["unit_oid"])
            rows, alias = _price_lookup(conn, v["id"])
            tpls = [t for t in templates if t["vendor"] == v["name"]]
            vc = [c for t in tpls for c in template_candidates(t, items, rows, alias, ok)]
            vc += simple_candidates(items, rows, alias, {t["price_item"] for t in tpls}, ok)
            opens = hours.opens_within(v["hours"], at, timedelta(hours=2)) if soon else None
            for c in vc:
                c.update(sum_macros(c["components"]))
                c["points_cost"] = round(c["price"] * (1 + TAX), 2)
                c.update(vendor_id=v["id"], vendor=v["name"], opens_at=opens.isoformat() if opens else None)
                s_ = score(c, p_s, c_s, headroom, hist.get(v["id"], 0) / n_orders, bias, ref_price)
                c["score"] = round(s_ - (ATE_HERE_TODAY if v["id"] in today_vendors else 0.0), 4)
            vc = [c for c in vc if c["calories"] >= MIN_MEAL_SHARE * c_s]
            out += sorted(vc, key=lambda c: -c["score"])[:CAP_PER_VENDOR]
        return out

    # Places open now; if none of them has a meal we can price (e.g. only breakfast spots at
    # 10:30), places opening within 2 hours, labeled with their opening time.
    cands = candidates([v for v in vendors if hours.is_open(v["hours"], at)], soon=False)
    fallback = not cands
    if fallback:
        cands = candidates([v for v in vendors if hours.opens_within(v["hours"], at, timedelta(hours=2))], soon=True)
    elif len({c["vendor_id"] for c in cands}) < 2:
        # One place open (Sunday 10:30: only The Skillet): also offer places opening within the
        # hour, labeled with their opening time, so the tabs aren't all the same breakfast.
        cands += candidates([v for v in vendors if hours.opens_within(v["hours"], at, timedelta(hours=1))
                             and not hours.is_open(v["hours"], at)], soon=True)
    picks = pick_top(cands)
    if not s.show_calories:
        for p in picks:
            p["calories"] = None
            for c in p["components"]:
                c["calories"] = None
    return {
        "user_id": user_id, "bias": bias, "at": at.isoformat(), "meals_left": meals_left,
        "per_meal_target": {"protein_g": round(p_t, 1), "calories": round(c_t) if s.show_calories else None},
        "headroom": None if headroom is None else round(headroom, 2),
        "restrictions": {"require_diets": s.require_diets, "avoid_allergens": s.avoid_allergens},
        "open_fallback": fallback, "candidates": len(cands), "picks": picks, "coach": None,
        "show_calories": s.show_calories,
    }
