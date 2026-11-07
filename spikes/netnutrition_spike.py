"""NetNutrition spike: dump one or more units to JSON.

Usage:
  .venv/bin/python spikes/netnutrition_spike.py 18 4 --out spikes/nn.json [--date 2026-11-07]

Verified from Python on 2026-11-07 (see docs/findings/netnutrition.md):
- Plain requests.Session works. Cookies from GET /nn-prod/Duke (ASP.NET_SessionId, AWSALB,
  CBORD.netnutrition2) are enough; no anti-forgery token exists.
- Panel HTML uses single-quoted attributes, so regexes accept either quote.
- Items with one serving size have no uofm <select>; the size is plain text. Stored with
  uofm_oid 0.
- ChangeUofM and the label call depend on session state (selected unit/menu, current
  serving size), so before any uncached label fetch we (re)select that unit/menu.

Politeness: sequential, >= 1 s between requests. Raw responses are cached in spikes/nn_cache/
(labels forever, unit/menu panels per day), so re-runs and parser fixes don't re-hit the site.
"""
import argparse, datetime as dt, html, json, re, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

BASE = "https://netnutrition.cbord.com/nn-prod/Duke"
CACHE = Path(__file__).with_name("nn_cache"); CACHE.mkdir(exist_ok=True)
UA = "thecube-hackathon/0.1 (Duke student project)"
Q = "[\"']"  # either quote
ALLERGENS = {"Egg": "egg", "Fish": "fish", "Gluten": "gluten", "Milk": "milk", "Peanut": "peanut",
             "Sesame": "sesame", "Shellfish": "shellfish", "Soy": "soy", "Tree Nut": "tree_nut",
             "Wheat": "wheat"}
DIETS = {"Halal": "halal", "Vegan": "vegan", "Vegetarian": "vegetarian"}


class Client:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.headers["X-Requested-With"] = "XMLHttpRequest"
        self.last = 0.0
        self.context = None   # ("unit", oid) or ("menu", oid) currently selected in the session
        self.requests = 0
        self.started = False

    def _wait(self):
        d = time.monotonic() - self.last
        if d < 1.0: time.sleep(1.0 - d)
        self.last = time.monotonic(); self.requests += 1

    def start(self):
        if self.started: return
        self._wait()
        r = self.s.get(BASE, timeout=30); r.raise_for_status()
        self.started = True
        return r.text

    def post(self, path, **data):
        self.start()
        self._wait()
        r = self.s.post(f"{BASE}/{path}", data=data, timeout=30)
        r.raise_for_status()
        return r


C = Client()


def cached(name, fetch):
    f = CACHE / name
    if f.exists(): return f.read_text()
    body = fetch(); f.write_text(body); return body


def text(fragment):
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def num(pattern, s):
    m = re.search(pattern, s)
    if not m: return None
    v = m.group(1).strip()
    if v.startswith("<"): return 0.5
    try: return float(v)
    except ValueError: return None


def parse_label(h):
    t = text(h)
    ss = re.search(r"Serving Size\s*(.+?)\s*\((\d+(?:\.\d+)?)\s*g\)", t)
    ing = re.search(r"Ingredients:\s*(.+?)\s*\* The % Daily Value", t)
    return {
        "serving": ss.group(1) if ss else None, "grams": float(ss.group(2)) if ss else None,
        "calories": num(r"Calories\s*([\d.]+)", t),
        "fat_g": num(r"Total Fat\s*(<?\s*[\d.]+)\s*g", t),
        "carbs_g": num(r"Total Carbohydrate\s*(<?\s*[\d.]+)\s*g", t),
        "protein_g": num(r"Protein\s*(<?\s*[\d.]+)\s*g", t),
        "fiber_g": num(r"Dietary Fiber\s*(<?\s*[\d.]+)\s*g", t),
        "sugar_g": num(r"Total Sugars\s*(<?\s*[\d.]+)\s*g", t),
        "sodium_mg": num(r"Sodium\s*(<?\s*[\d.]+)\s*mg", t),
        "ingredients": ing.group(1) if ing else None,
    }


def panels(body):
    return {p["id"]: p.get("html") or "" for p in json.loads(body)["panels"]}


def parse_items(panel_html):
    courses = {cid: text(name) for cid, name in re.findall(
        r"toggleCourseItems\(this,\s*(\d+)\);?" + Q + r"[^>]*>(.*?)</tr>", panel_html, flags=re.S)}
    items = []
    for cat, row in re.findall(r"<tr[^>]*data-categoryid=" + Q + r"(\d+)" + Q + r"[^>]*>(.*?)</tr>",
                               panel_html, flags=re.S):
        m = re.search(r"id=" + Q + r"showNutrition_(\d+)" + Q + r"[^>]*>(.*?)</a>", row, flags=re.S)
        if not m: continue
        oid, inner = m.groups()
        name = text(inner.split("<span")[0])
        traits = re.findall(r"<img[^>]*title=" + Q + r"([^\"']+)" + Q, inner)
        sel = re.search(r"<select[^>]*id=" + Q + r"uofm%s" % oid + Q + r"[^>]*>(.*?)</select>", row, flags=re.S)
        if sel:
            portions = [{"uofm_oid": int(v), "name": text(n), "default": "selected" in a}
                        for a, v, n in re.findall(r"<option([^>]*)value=" + Q + r"(\d+)" + Q + r"[^>]*>(.*?)</option>",
                                                  sel.group(1))]
        else:  # single serving size: 2nd cell is plain text
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
            size = text(cells[2]) if len(cells) > 2 else ""
            portions = [{"uofm_oid": 0, "name": size, "default": True}]
        items.append({
            "item_oid": int(oid), "name": name, "course": courses.get(cat, ""),
            "allergens": sorted(ALLERGENS[t] for t in traits if t in ALLERGENS),
            "diets": sorted(DIETS[t] for t in traits if t in DIETS),
            "other_traits": sorted(t for t in traits if t not in ALLERGENS and t not in DIETS),
            "portions": portions})
    return items


def parse_menu_list(menu_html):
    """-> [(date, meal, menuOid)] from the dining-hall menu list."""
    out = []
    for card in re.split(r"<header[^>]*card-title[^>]*>", menu_html)[1:]:
        day = text(card.split("</header>")[0])
        try: d = dt.datetime.strptime(day, "%A, %B %d, %Y").date()
        except ValueError: d = None
        for oid, meal in re.findall(r"menuListSelectMenu\((\d+)\);?" + Q + r"[^>]*>(.*?)</a>", card, flags=re.S):
            out.append((d, text(meal), int(oid)))
    return out


def ensure_context(ctx):
    """Make the server session point at this unit/menu before label/UofM calls."""
    if C.context == ctx: return
    kind, oid = ctx
    if kind == "unit":
        C.post("Unit/SelectUnitFromUnitsList", unitOid=oid)
    else:
        unit_oid, menu_oid = oid
        C.post("Unit/SelectUnitFromUnitsList", unitOid=unit_oid)
        C.post("Menu/SelectMenu", menuOid=menu_oid)
    C.context = ctx


def label(item, portion, ctx, menu_oid=None):
    f = CACHE / f"{item['item_oid']}_{portion['uofm_oid']}.html"
    if f.exists(): return f.read_text()
    ensure_context(ctx)
    if portion["uofm_oid"]:  # always set explicitly: session remembers the last size per item
        C.post("Menu/ChangeUofM", detailOid=item["item_oid"], uofmOid=portion["uofm_oid"])
    data = {"detailOid": item["item_oid"]}
    if menu_oid: data["menuOid"] = menu_oid
    h = C.post("NutritionDetail/ShowItemNutritionLabel", **data).text
    f.write_text(h); return h


def fill_labels(items, ctx, menu_oid=None):
    problems = []
    for it in items:
        for p in sorted(it["portions"], key=lambda p: not p["default"]):
            lab = parse_label(label(it, p, ctx, menu_oid))
            p.update({k: lab[k] for k in ("grams", "calories", "protein_g", "carbs_g", "fat_g",
                                          "fiber_g", "sugar_g", "sodium_mg")})
            p["label_serving"] = lab["serving"]
            it.setdefault("ingredients", lab["ingredients"])
            if p["uofm_oid"] and lab["serving"] != p["name"]:
                problems.append(f"{it['name']}: asked {p['name']!r}, label says {lab['serving']!r}")
            if lab["calories"] is None:
                problems.append(f"{it['name']} / {p['name']}: no calories parsed")
        print(f"  {it['name']}: {[(p['name'], p['calories'], p['protein_g']) for p in it['portions']]}",
              file=sys.stderr)
    return problems


def scrape_unit(u, unit_names, today):
    tag = today.isoformat()
    def fetch_unit():
        r = C.post("Unit/SelectUnitFromUnitsList", unitOid=u).text
        C.context = ("unit", u); return r
    pn = panels(cached(f"unit_{u}_{tag}.json", fetch_unit))
    unit = {"unit_oid": u, "name": unit_names.get(u), "kind": None, "menus": [], "items": [], "problems": []}
    if "showNutrition_" in pn.get("itemPanel", ""):
        unit["kind"] = "retail"
        unit["items"] = parse_items(pn["itemPanel"])
        unit["problems"] = fill_labels(unit["items"], ("unit", u))
    else:
        unit["kind"] = "dining_hall"
        menus = parse_menu_list(pn.get("menuPanel", ""))
        unit["menus"] = [{"date": d.isoformat() if d else None, "meal": m, "menu_oid": o} for d, m, o in menus]
        for d, meal, menu_oid in menus:
            if d != today: continue
            print(f" menu {menu_oid} {d} {meal}", file=sys.stderr)
            def fetch():
                ensure_context(("unit", u))
                r = C.post("Menu/SelectMenu", menuOid=menu_oid).text
                C.context = ("menu", (u, menu_oid)); return r
            mp = panels(cached(f"menu_{menu_oid}.json", fetch))
            items = parse_items(mp.get("itemPanel", ""))
            for it in items: it.update(menu_date=d.isoformat(), meal=meal, menu_oid=menu_oid)
            unit["problems"] += fill_labels(items, ("menu", (u, menu_oid)), menu_oid)
            unit["items"] += items
    return unit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units", nargs="*", type=int, default=[18])
    ap.add_argument("--out")
    ap.add_argument("--date", help="dining-hall menu date (default: today in America/New_York)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(ZoneInfo("America/New_York")).date()
    home = cached(f"home_{today.isoformat()}.html", C.start)
    unit_names = {int(u): text(n) for u, n in re.findall(
        r"unitsSelectUnit\((\d+)\);?" + Q + r"[^>]*>(.*?)</a>", home, flags=re.S)}
    out = {"scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "menu_date": today.isoformat(), "all_units": unit_names, "units": []}
    for u in a.units:
        print(f"unit {u} {unit_names.get(u)}", file=sys.stderr)
        unit = scrape_unit(u, unit_names, today)
        n_p = sum(len(i["portions"]) for i in unit["items"])
        print(f"unit {u}: {unit['kind']}, {len(unit['items'])} items, {n_p} portions, "
              f"{len(unit['problems'])} problems", file=sys.stderr)
        for p in unit["problems"]: print("   !", p, file=sys.stderr)
        out["units"].append(unit)
    print(f"network requests this run: {C.requests}", file=sys.stderr)
    s = json.dumps(out, indent=1, ensure_ascii=False)
    if a.out: Path(a.out).write_text(s)
    else: print(s)


if __name__ == "__main__":
    main()
