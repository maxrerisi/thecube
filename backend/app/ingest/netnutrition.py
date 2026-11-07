"""Duke NetNutrition scraper (SPEC 5; flow in docs/findings/netnutrition.md).

  python -m app.ingest.netnutrition --units 18,21 --out ../spikes/nn.json
  python -m app.ingest.netnutrition --all --write-db

Sequential, >= 1 s between requests, descriptive User-Agent. Raw responses cached under
spikes/nn_cache/ (labels forever, unit/menu panels per day), so re-runs are ~free.
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

BASE = "https://netnutrition.cbord.com/nn-prod/Duke"
UA = "thecube-hackathon/0.1 (Duke student project)"
CACHE = Path(__file__).resolve().parents[3] / "spikes" / "nn_cache"
NY = ZoneInfo("America/New_York")
Q = "[\"']"  # panel HTML uses single-quoted attributes
ALLERGENS = {"Egg": "egg", "Fish": "fish", "Gluten": "gluten", "Milk": "milk", "Peanut": "peanut",
             "Sesame": "sesame", "Shellfish": "shellfish", "Soy": "soy", "Tree Nut": "tree_nut",
             "Wheat": "wheat"}
DIETS = {"Halal": "halal", "Vegan": "vegan", "Vegetarian": "vegetarian"}
MACROS = ("grams", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- parsing (pure) ----------

def text(fragment: str) -> str:
    t = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _num(pattern, s):
    m = re.search(pattern, s)
    if not m:
        return None
    v = m.group(1).strip()
    if v.startswith("<"):
        return 0.5
    try:
        return float(v)
    except ValueError:
        return None


def parse_label(h: str) -> dict:
    t = text(h)
    ss = re.search(r"Serving Size\s*(.+?)\s*\((\d+(?:\.\d+)?)\s*g\)", t)
    ing = re.search(r"Ingredients:\s*(.+?)\s*\* The % Daily Value", t)
    return {
        "serving": ss.group(1) if ss else None, "grams": float(ss.group(2)) if ss else None,
        "calories": _num(r"Calories\s*([\d.]+)", t),
        "fat_g": _num(r"Total Fat\s*(<?\s*[\d.]+)\s*g", t),
        "carbs_g": _num(r"Total Carbohydrate\s*(<?\s*[\d.]+)\s*g", t),
        "protein_g": _num(r"Protein\s*(<?\s*[\d.]+)\s*g", t),
        "fiber_g": _num(r"Dietary Fiber\s*(<?\s*[\d.]+)\s*g", t),
        "sugar_g": _num(r"Total Sugars\s*(<?\s*[\d.]+)\s*g", t),
        "sodium_mg": _num(r"Sodium\s*(<?\s*[\d.]+)\s*mg", t),
        "ingredients": ing.group(1) if ing else None,
    }


def panels(body: str) -> dict:
    return {p["id"]: p.get("html") or "" for p in json.loads(body)["panels"]}


def parse_units(home_html: str) -> dict[int, str]:
    return {int(u): text(n) for u, n in re.findall(
        r"unitsSelectUnit\((\d+)\);?" + Q + r"[^>]*>(.*?)</a>", home_html, flags=re.S)}


def parse_items(panel_html: str) -> list[dict]:
    courses = {cid: text(name) for cid, name in re.findall(
        r"toggleCourseItems\(this,\s*(\d+)\);?" + Q + r"[^>]*>(.*?)</tr>", panel_html, flags=re.S)}
    items = []
    for cat, row in re.findall(r"<tr[^>]*data-categoryid=" + Q + r"(\d+)" + Q + r"[^>]*>(.*?)</tr>",
                               panel_html, flags=re.S):
        m = re.search(r"id=" + Q + r"showNutrition_(\d+)" + Q + r"[^>]*>(.*?)</a>", row, flags=re.S)
        if not m:
            continue
        oid, inner = m.groups()
        traits = re.findall(r"<img[^>]*title=" + Q + r"([^\"']+)" + Q, inner)
        sel = re.search(r"<select[^>]*id=" + Q + r"uofm%s" % oid + Q + r"[^>]*>(.*?)</select>", row, flags=re.S)
        if sel:
            portions = [{"uofm_oid": int(v), "name": text(n), "default": "selected" in a}
                        for a, v, n in re.findall(
                            r"<option([^>]*)value=" + Q + r"(\d+)" + Q + r"[^>]*>(.*?)</option>", sel.group(1))]
        else:  # one fixed serving: plain text in the 3rd cell, no uofmOid -> store as 0
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
            portions = [{"uofm_oid": 0, "name": text(cells[2]) if len(cells) > 2 else "", "default": True}]
        items.append({
            "item_oid": int(oid), "name": text(inner.split("<span")[0]), "course": courses.get(cat, ""),
            "allergens": sorted(ALLERGENS[t] for t in traits if t in ALLERGENS),
            "diets": sorted(DIETS[t] for t in traits if t in DIETS),
            "other_traits": sorted(t for t in traits if t not in ALLERGENS and t not in DIETS),
            "portions": portions})
    return items


def parse_menu_list(menu_html: str) -> list[tuple]:
    """-> [(date | None, meal, menuOid)]"""
    out = []
    for card in re.split(r"<header[^>]*card-title[^>]*>", menu_html)[1:]:
        day = text(card.split("</header>")[0])
        try:
            d = dt.datetime.strptime(day, "%A, %B %d, %Y").date()
        except ValueError:
            d = None
        for oid, meal in re.findall(r"menuListSelectMenu\((\d+)\);?" + Q + r"[^>]*>(.*?)</a>", card, flags=re.S):
            out.append((d, text(meal), int(oid)))
    return out


# ---------- network ----------

class Scraper:
    def __init__(self, cache: Path = CACHE):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.headers["X-Requested-With"] = "XMLHttpRequest"
        self.last = 0.0
        self.started = False
        self.context = None  # what the server session currently has selected
        self.requests = 0

    def _wait(self):
        d = time.monotonic() - self.last
        if d < 1.0:
            time.sleep(1.0 - d)
        self.last = time.monotonic()
        self.requests += 1

    def _start(self) -> str:
        self._wait()
        r = self.s.get(BASE, timeout=30)
        r.raise_for_status()
        self.started = True
        return r.text

    def post(self, path, **data) -> str:
        if not self.started:
            self._start()
        self._wait()
        r = self.s.post(f"{BASE}/{path}", data=data, timeout=30)
        r.raise_for_status()
        return r.text

    def cached(self, name, fetch) -> str:
        f = self.cache / name
        if f.exists():
            return f.read_text()
        body = fetch()
        f.write_text(body)
        return body

    def home(self, day: dt.date) -> str:
        return self.cached(f"home_{day.isoformat()}.html", self._start)

    def _select(self, ctx):
        if self.context == ctx:
            return
        unit_oid, menu_oid = ctx
        self.post("Unit/SelectUnitFromUnitsList", unitOid=unit_oid)
        if menu_oid:
            self.post("Menu/SelectMenu", menuOid=menu_oid)
        self.context = ctx

    def label(self, item, portion, ctx) -> str:
        f = self.cache / f"{item['item_oid']}_{portion['uofm_oid']}.html"
        if f.exists():
            return f.read_text()
        self._select(ctx)
        if portion["uofm_oid"]:  # the session remembers the last size per item: always set it
            self.post("Menu/ChangeUofM", detailOid=item["item_oid"], uofmOid=portion["uofm_oid"])
        data = {"detailOid": item["item_oid"]}
        if ctx[1]:
            data["menuOid"] = ctx[1]
        h = self.post("NutritionDetail/ShowItemNutritionLabel", **data)
        f.write_text(h)
        return h

    def fill_labels(self, items, ctx) -> list[str]:
        problems = []
        for it in items:
            for p in sorted(it["portions"], key=lambda p: not p["default"]):
                lab = parse_label(self.label(it, p, ctx))
                p.update({k: lab[k] for k in MACROS})
                p["label_serving"] = lab["serving"]
                it.setdefault("ingredients", lab["ingredients"])
                if p["uofm_oid"] and lab["serving"] != p["name"]:
                    problems.append(f"{it['name']}: asked {p['name']!r}, label says {lab['serving']!r}")
                if lab["calories"] is None:
                    problems.append(f"{it['name']} / {p['name']}: no calories parsed")
        return problems

    def scrape_unit(self, u: int, name: str | None, day: dt.date) -> dict:
        def fetch_unit():
            body = self.post("Unit/SelectUnitFromUnitsList", unitOid=u)
            self.context = (u, None)
            return body
        pn = panels(self.cached(f"unit_{u}_{day.isoformat()}.json", fetch_unit))
        unit = {"unit_oid": u, "name": name, "kind": None, "menus": [], "items": [], "problems": []}
        if "showNutrition_" in pn.get("itemPanel", ""):
            unit["kind"] = "retail"
            unit["items"] = parse_items(pn["itemPanel"])
            unit["problems"] = self.fill_labels(unit["items"], (u, None))
        else:
            unit["kind"] = "dining_hall"
            menus = parse_menu_list(pn.get("menuPanel", ""))
            unit["menus"] = [{"date": d.isoformat() if d else None, "meal": m, "menu_oid": o} for d, m, o in menus]
            for d, meal, menu_oid in menus:
                if d != day:
                    continue
                def fetch_menu(menu_oid=menu_oid):
                    self._select((u, None))
                    body = self.post("Menu/SelectMenu", menuOid=menu_oid)
                    self.context = (u, menu_oid)
                    return body
                items = parse_items(panels(self.cached(f"menu_{menu_oid}.json", fetch_menu)).get("itemPanel", ""))
                for it in items:
                    it.update(menu_date=d.isoformat(), meal=meal, menu_oid=menu_oid)
                unit["problems"] += self.fill_labels(items, (u, menu_oid))
                unit["items"] += items
        return unit


def scrape(unit_oids: list[int] | None, day: dt.date | None = None) -> dict:
    """unit_oids None = all units on the home page."""
    day = day or dt.datetime.now(NY).date()
    sc = Scraper()
    names = parse_units(sc.home(day))
    out = {"scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "menu_date": day.isoformat(), "all_units": names, "units": []}
    for u in unit_oids or sorted(names):
        unit = sc.scrape_unit(u, names.get(u), day)
        log(f"unit {u} {unit['name']}: {unit['kind']}, {len(unit['items'])} items, "
            f"{sum(len(i['portions']) for i in unit['items'])} portions, {len(unit['problems'])} problems")
        for p in unit["problems"]:
            log("   !", p)
        out["units"].append(unit)
    log(f"network requests: {sc.requests}")
    return out


# ---------- DB ----------

def write_db(conn, data: dict) -> dict:
    """Upsert nn_units / nn_items / nn_portions. Never deletes (orders reference old item_oids)."""
    n_items = n_portions = 0
    for u in data["units"]:
        conn.execute(
            """INSERT INTO nn_units (unit_oid, name, kind) VALUES (%s, %s, %s)
               ON CONFLICT (unit_oid) DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind""",
            (u["unit_oid"], u["name"] or f"unit {u['unit_oid']}", u["kind"]))
        for it in u["items"]:
            conn.execute(
                """INSERT INTO nn_items (item_oid, unit_oid, course, name, allergens, diets, ingredients,
                                         menu_date, meal, scraped_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT (item_oid) DO UPDATE SET unit_oid = EXCLUDED.unit_oid, course = EXCLUDED.course,
                     name = EXCLUDED.name, allergens = EXCLUDED.allergens, diets = EXCLUDED.diets,
                     ingredients = EXCLUDED.ingredients, menu_date = EXCLUDED.menu_date,
                     meal = EXCLUDED.meal, scraped_at = now()""",
                (it["item_oid"], u["unit_oid"], it["course"], it["name"], it["allergens"], it["diets"],
                 it.get("ingredients"), it.get("menu_date"), it.get("meal")))
            n_items += 1
            for p in it["portions"]:
                conn.execute(
                    """INSERT INTO nn_portions (item_oid, uofm_oid, portion_name, is_default, grams, calories,
                                                protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (item_oid, uofm_oid) DO UPDATE SET portion_name = EXCLUDED.portion_name,
                         is_default = EXCLUDED.is_default, grams = EXCLUDED.grams, calories = EXCLUDED.calories,
                         protein_g = EXCLUDED.protein_g, carbs_g = EXCLUDED.carbs_g, fat_g = EXCLUDED.fat_g,
                         fiber_g = EXCLUDED.fiber_g, sugar_g = EXCLUDED.sugar_g, sodium_mg = EXCLUDED.sodium_mg""",
                    (it["item_oid"], p["uofm_oid"], p["name"], p["default"],
                     *(p.get(k) for k in MACROS)))
                n_portions += 1
    return {"units": len(data["units"]), "items": n_items, "portions": n_portions}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--units", help="comma-separated unitOids, e.g. 18,21")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--out", help="write JSON here")
    ap.add_argument("--write-db", action="store_true")
    ap.add_argument("--date", help="menu date YYYY-MM-DD (default: today, America/New_York)")
    a = ap.parse_args(argv)
    units = None if a.all else [int(x) for x in a.units.split(",")]
    data = scrape(units, dt.date.fromisoformat(a.date) if a.date else None)
    if a.out:
        Path(a.out).write_text(json.dumps(data, indent=1, ensure_ascii=False))
    if a.write_db:
        from app.db import connect, init_schema
        with connect() as conn:
            init_schema(conn)
            log("db:", write_db(conn, data))
    if not a.out and not a.write_db:
        print(json.dumps(data, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()


# ---------- hours ----------

DAYS = {"Sunday": "sun", "Monday": "mon", "Tuesday": "tue", "Wednesday": "wed", "Thursday": "thu",
        "Friday": "fri", "Saturday": "sat"}


def parse_hours(h: str) -> dict[str, list[list[str]]]:
    """GetHoursOfOperationMarkup -> {"mon": [["11:00", "21:00"]], ...} (24h, local). Days with
    no row are closed (absent)."""
    out: dict[str, list[list[str]]] = {}
    for day, opens, closes in re.findall(r"<tr[^>]*>\s*<td>(\w+)</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>", h):
        if day not in DAYS:
            continue
        try:
            o = dt.datetime.strptime(opens.strip(), "%I:%M %p").strftime("%H:%M")
            c = dt.datetime.strptime(closes.strip(), "%I:%M %p").strftime("%H:%M")
        except ValueError:
            continue  # "Closed" etc.
        out.setdefault(DAYS[day], []).append([o, c])
    return out


def hours(sc: "Scraper", unit_oid: int, day: dt.date) -> dict:
    return parse_hours(sc.cached(f"hours_{unit_oid}_{day.isoformat()}.html",
                                 lambda: sc.post("Unit/GetHoursOfOperationMarkup", unitOid=unit_oid)))
