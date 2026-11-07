"""Receipt names -> vendors and NetNutrition items (SPEC 6 pipeline steps 2, 4, 5).

Tightened per E3 (docs/findings/matching.md), approved 2026-11-07:
- vendor fuzzy: token_set_ratio >= 85 with a clear winner; never auto-written as an alias
  (WRatio >= 85 mapped McDonald's -> J.B.'s and Devil's Krafthouse -> It's Thyme).
- component fuzzy: token_set_ratio >= 90 and no differently-named item within 3 points;
  only then is the alias written. Word-subset ties ("Whole", "Chicken") and near misses
  ("Sweet Potato Chips" -> "Sweet Potato Fries", 83) stay NULL and are reported.
"""
import re

from rapidfuzz import fuzz, process, utils

VENDOR_THRESHOLD = 85   # token_set_ratio vs vendors.name
ITEM_THRESHOLD = 90     # token_set_ratio within the vendor's unit
TIE_GAP = 3             # a different name scoring within this many points = ambiguous
FORMATS = [("arepa bowl", "arepa_bowl"), ("burrito", "burrito"), ("quesadilla", "quesadilla"), ("taco", "taco")]
FORMAT_WORD = {"arepa_bowl": "arepa", "burrito": "burrito", "quesadilla": "quesadilla", "taco": "taco"}


def key(s: str) -> str:
    """Alias key: lowercased, whitespace collapsed ("Farmstead  &  Sprout" -> "farmstead & sprout")."""
    return " ".join(s.lower().split())


def norm(s: str) -> str:
    s = re.sub(r"\s*-\s*(toppings|base)\s*$", "", s, flags=re.I)  # Gyotaku "Cucumber - Toppings"
    return utils.default_process(s)


def item_format(item_name: str) -> str | None:
    n = item_name.lower()
    return next((f for k, f in FORMATS if k in n), None)


def resolve_vendor(conn, raw: str) -> dict | None:
    """-> vendors row (id, name, unit_oid) or None."""
    row = conn.execute("""SELECT v.id, v.name, v.unit_oid FROM vendor_aliases a JOIN vendors v ON v.id = a.vendor_id
                          WHERE a.raw = %s""", (key(raw),)).fetchone()
    if row:
        return row
    vendors = conn.execute("SELECT id, name, unit_oid FROM vendors").fetchall()
    res = process.extract(raw, {v["id"]: v["name"] for v in vendors}, scorer=fuzz.token_set_ratio,
                          processor=utils.default_process, limit=2)
    if not res or res[0][1] < VENDOR_THRESHOLD:
        return None
    if len(res) > 1 and res[0][1] - res[1][1] <= TIE_GAP:
        return None  # ambiguous
    return next(v for v in vendors if v["id"] == res[0][2])  # not persisted: add real aliases to the seed


def _has_format(portion_names: list[str], fmt: str | None) -> bool:
    return bool(fmt) and any(FORMAT_WORD[fmt] in p.lower().split() for p in portion_names)


def match_component(conn, vendor: dict, raw: str, fmt: str | None) -> int | None:
    """-> item_oid or None. Writes an item alias on a fuzzy hit (SPEC 6 step 5)."""
    if not vendor or vendor["unit_oid"] is None:
        return None
    row = conn.execute("SELECT item_oid FROM item_aliases WHERE vendor_id = %s AND raw = %s",
                       (vendor["id"], key(raw))).fetchone()
    if row:
        return row["item_oid"]
    cands = conn.execute(
        """SELECT i.item_oid, i.name, array_agg(p.portion_name) AS portions
           FROM nn_items i JOIN nn_portions p USING (item_oid)
           WHERE i.unit_oid = %s GROUP BY i.item_oid, i.name, i.menu_date, i.scraped_at
           ORDER BY i.menu_date DESC NULLS LAST, i.scraped_at DESC, i.item_oid""",
        (vendor["unit_oid"],)).fetchall()
    if not cands:
        return None
    q = norm(raw)
    scored = [(fuzz.token_set_ratio(q, norm(c["name"])), c) for c in cands]
    # equal scores: prefer an item with a portion for this format (topping vs side), then
    # closer plain ratio, then the newest menu (list is already newest-first; sort is stable)
    scored.sort(key=lambda sc: (-sc[0], not _has_format(sc[1]["portions"], fmt),
                                -fuzz.ratio(q, norm(sc[1]["name"]))))
    score, best = scored[0]
    if score < ITEM_THRESHOLD:
        return None
    if any(c["name"] != best["name"] and score - s <= TIE_GAP for s, c in scored[1:]):
        return None  # ambiguous: e.g. "Whole" = Latte Whole Milk = Steamer Whole Milk
    conn.execute("""INSERT INTO item_aliases (vendor_id, raw, item_oid) VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING""", (vendor["id"], key(raw), best["item_oid"]))
    return best["item_oid"]


def pick_portion(conn, item_oid: int, fmt: str | None) -> int | None:
    """-> uofm_oid: the portion named for the format ("Burrito Portion", "Arepa Portion", "Arepa"), else default."""
    rows = conn.execute("SELECT uofm_oid, portion_name, is_default FROM nn_portions WHERE item_oid = %s",
                        (item_oid,)).fetchall()
    if fmt:
        hit = next((r for r in rows if FORMAT_WORD[fmt] in r["portion_name"].lower().split()), None)
        if hit:
            return hit["uofm_oid"]
    default = next((r for r in rows if r["is_default"]), rows[0] if rows else None)
    return default["uofm_oid"] if default else None
