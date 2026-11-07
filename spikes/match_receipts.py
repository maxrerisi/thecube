"""E3: match receipt items/components to NetNutrition items (SPEC section 6).

Usage: .venv/bin/python spikes/match_receipts.py [spikes/receipts.json] [spikes/nn.json] [seed/aliases.json]
Writes spikes/matching.json (per-line detail) and prints a summary.

Rules (from SPEC 6):
- vendor: alias exact (lowercased), else rapidfuzz WRatio >= 85 vs NetNutrition unit names.
- component: item alias exact, else token_set_ratio >= 80 within the vendor's unit.
- a line is "ambiguous" if a different-named candidate also scores within 3 points of the best.
- format from item name -> portion containing the format, else the default portion.
"""
import json, re, sys
from pathlib import Path
from rapidfuzz import fuzz, process, utils

RECEIPTS = Path(sys.argv[1] if len(sys.argv) > 1 else "spikes/receipts.json")
NN = Path(sys.argv[2] if len(sys.argv) > 2 else "spikes/nn.json")
ALIASES = Path(sys.argv[3]) if len(sys.argv) > 3 else None
VENDOR_T, ITEM_T, AMBIG_GAP = 85, 80, 3
FORMATS = [("arepa bowl", "Arepa Bowl"), ("burrito", "Burrito"), ("quesadilla", "Quesadilla"), ("taco", "Taco")]


def norm(s):
    s = re.sub(r"\s*-\s*(toppings|base)\s*$", "", s, flags=re.I)  # Gyotaku "Cucumber - Toppings"
    return utils.default_process(s)


def fmt(item_name):
    n = item_name.lower()
    return next((f for k, f in FORMATS if k in n), None)


def main():
    receipts = json.loads(RECEIPTS.read_text())
    nn = json.loads(NN.read_text())
    units = {u["unit_oid"]: u for u in nn["units"]}
    unit_names = {int(k): v for k, v in nn["all_units"].items()}
    aliases = json.loads(ALIASES.read_text()) if ALIASES and ALIASES.exists() else {"vendors": [], "items": {}}
    valias = {a: v for v in aliases["vendors"] for a in v["aliases"]}

    def vendor_unit(raw):
        key = " ".join(raw.lower().split())
        if key in valias:
            v = valias[key]
            return v["unit_oid"], v["name"], 100.0, "alias"
        best = process.extractOne(raw, unit_names, scorer=fuzz.WRatio, processor=utils.default_process)
        if best and best[1] >= VENDOR_T:
            return best[2], best[0], best[1], "fuzzy"
        return None, best[0] if best else None, best[1] if best else 0, "none"

    def match(raw, unit, vendor_key):
        items = unit["items"]
        ali = aliases["items"].get(vendor_key, {}).get(" ".join(raw.lower().split()))
        if ali is not None:
            name, course = (ali, "") if isinstance(ali, str) else (ali["name"], ali.get("course", ""))
            hit = next((i for i in items if i["name"] == name and course in i["course"]), None)
            ali = name
            return {"status": "alias" if hit else "alias_missing", "best": ali, "score": 100.0,
                    "item": hit, "second": None}
        choices = {i["item_oid"]: norm(i["name"]) for i in items}
        res = process.extract(norm(raw), choices, scorer=fuzz.token_set_ratio, processor=None, limit=12)
        if not res:
            return {"status": "unmatched", "best": None, "score": 0, "item": None, "second": None}
        by_oid = {i["item_oid"]: i for i in items}
        # tie-break equal token_set scores: prefer an item with a portion for this format
        # (topping "Pico de Gallo" over side "Pico de Gallo"), then plain ratio.
        res.sort(key=lambda r: (-r[1], not has_fmt(by_oid_all[r[2]], fmt_now[0]), -fuzz.ratio(norm(raw), r[0])))
        top = by_oid[res[0][2]]
        second = next(((by_oid[o]["name"], s) for _, s, o in res[1:]
                       if by_oid[o]["name"] != top["name"]), None)
        score = res[0][1]
        if score < ITEM_T: status = "unmatched"
        elif second and second[1] >= ITEM_T and score - second[1] <= AMBIG_GAP: status = "ambiguous"
        elif score < 90: status = "low"
        else: status = "ok"
        return {"status": status, "best": top["name"], "score": round(score, 1), "item": top,
                "second": [second[0], round(second[1], 1)] if second else None,
                "ratio": round(fuzz.ratio(norm(raw), norm(top["name"])), 1)}

    def portion(item, f):
        if not item: return None
        ps = item["portions"]
        # portion names vary: "Arepa Bowl Portion" / "Arepa Portion" / "Arepa"; match the keyword
        hit = next((p for p in ps if f and f.split()[0].lower() in p["name"].lower().split()), None)
        return hit or next(p for p in ps if p["default"])

    lines, orders = [], []
    by_oid_all = {i["item_oid"]: i for u in nn["units"] for i in u["items"]}
    fmt_now = [None]  # format of the receipt item currently being matched

    def has_fmt(item, f):
        return bool(f) and any(f.split()[0].lower() in p["name"].lower().split() for p in item["portions"])

    for r in receipts:
        uoid, uname, vscore, vhow = vendor_unit(r["vendor"])
        unit = units.get(uoid) if uoid else None
        vkey = uname
        o = {"order": r["order_number"], "vendor": r["vendor"], "unit_oid": uoid, "unit": uname,
             "vendor_score": round(vscore, 1), "vendor_how": vhow, "lines": 0, "matched": 0,
             "protein_g": 0.0, "calories": 0.0}
        for it in r["items"]:
            f = fmt(it["name"]); fmt_now[0] = f
            # What macros come from: the components if any, else the item itself (SPEC 4 note).
            # Items whose name is a dish with add-ons (e.g. "Biscuit Egg Cheese with Protein")
            # also get the item line matched, reported with role=item.
            targets = [("component", c["name"]) for c in it["components"]] or [("item", it["name"])]
            if it["components"]:
                targets.append(("item_with_components", it["name"]))
            for role, raw in targets:
                rec = {"order": r["order_number"], "vendor": r["vendor"], "unit": uname, "role": role,
                       "item": it["name"], "raw": raw, "format": f}
                if not unit:
                    rec.update(status="no_unit", best=None, score=None, second=None)
                else:
                    m = match(raw, unit, vkey)
                    p = portion(m["item"] if m["status"] != "unmatched" else None, f)
                    rec.update({k: v for k, v in m.items() if k != "item"})
                    rec["portion"] = p["name"] if p else None
                    if p and role != "item_with_components":
                        o["protein_g"] += p.get("protein_g") or 0; o["calories"] += p.get("calories") or 0
                if role != "item_with_components":
                    o["lines"] += 1
                    o["matched"] += rec["status"] in ("ok", "low", "ambiguous", "alias")
                lines.append(rec)
        o["full"] = bool(unit) and o["matched"] == o["lines"]
        o["full_confident"] = o["full"] and all(
            l["status"] in ("ok", "alias") for l in lines
            if l["order"] == r["order_number"] and l["role"] != "item_with_components")
        orders.append(o)

    Path("spikes/matching.json").write_text(json.dumps({"orders": orders, "lines": lines}, indent=1))
    macro_lines = [l for l in lines if l["role"] != "item_with_components"]
    st = {}
    for l in macro_lines: st[l["status"]] = st.get(l["status"], 0) + 1
    with_unit = [l for l in macro_lines if l["status"] != "no_unit"]
    print("vendors:", sorted({(o["vendor"], o["unit"], o["vendor_score"], o["vendor_how"]) for o in orders}, key=str))
    print("macro lines by status:", st)
    print(f"matched (ok/low/ambiguous/alias) at vendors with a unit: "
          f"{sum(l['status'] in ('ok','low','ambiguous','alias') for l in with_unit)}/{len(with_unit)}")
    print(f"orders with full macros: {sum(o['full'] for o in orders)}/{len(orders)}; "
          f"all-confident: {sum(o['full_confident'] for o in orders)}/{len(orders)}")
    print("\nNON-OK LINES (role, vendor, raw -> best score | second | portion):")
    seen = set()
    for l in lines:
        if l["status"] in ("ok", "alias", "no_unit"): continue
        k = (l["vendor"], l["raw"], l["role"])
        if k in seen: continue
        seen.add(k)
        print(f"  {l['status']:9} {l['role']:20} {l['vendor']:12} {l['raw']!r:42} -> {l['best']!r} {l['score']}"
              f" | {l.get('second')} | {l.get('portion')}")
    print("\nOK LINES:")
    seen = set()
    for l in lines:
        if l["status"] not in ("ok", "alias"): continue
        k = (l["vendor"], l["raw"])
        if k in seen: continue
        seen.add(k)
        print(f"  {l['vendor']:12} {l['raw']!r:40} -> {l['best']!r} {l['score']} r={l.get('ratio')} | {l.get('second')} | {l.get('portion')}")
    print("\nNO UNIT:", sorted({(l["vendor"], l["raw"]) for l in lines if l["status"] == "no_unit"}))


if __name__ == "__main__":
    main()
