"""T6 done-when: manual order for a Sazon burrito computes macros. Plus /vendors, menu, delete."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.hours import is_open, opens_within
from conftest import AUTH


def vid(client, name):
    return next(v["id"] for v in client.get("/vendors", headers=AUTH).json() if v["name"] == name)


def find(menu, name, course=None):
    return next(i for c in menu["courses"] for i in c["items"]
                if i["name"] == name and (course is None or c["name"] == course))


def portion(item, word):
    return next(p for p in item["portions"] if word in p["name"].lower().split())


def test_vendors(menus):
    vs = menus.get("/vendors", headers=AUTH).json()
    assert len(vs) == 12
    sazon = next(v for v in vs if v["name"] == "Sazon")
    assert sazon["has_nutrition"] and sazon["hours"]["mon"] == [["11:00", "21:00"]]
    assert not next(v for v in vs if v["name"] == "Gothic Grill")["has_nutrition"]


def test_menu_by_course_with_traits(menus):
    m = menus.get(f"/vendors/{vid(menus, 'Sazon')}/menu", headers=AUTH).json()
    names = [c["name"] for c in m["courses"]]
    assert "Choose Protein" in names and "Choose Sauce" in names
    cc = find(m, "Chipotle Chicken")
    assert cc["diets"] == ["halal"] and len(cc["portions"]) == 4 and cc["portions"][0]["is_default"]


def test_manual_sazon_burrito_macros(menus):
    sazon = vid(menus, "Sazon")
    m = menus.get(f"/vendors/{sazon}/menu", headers=AUTH).json()
    picks = [find(m, 'Flour Tortilla 12"'), find(m, "Cilantro Lime White Rice"),
             find(m, "Chipotle Chicken"), find(m, "Black Beans"), find(m, "Pico de Gallo", "Choose Topping")]
    items, exp = [], {"calories": 0, "protein_g": 0}
    for it in picks:
        p = portion(it, "burrito")
        items.append({"item_oid": it["item_oid"], "uofm_oid": p["uofm_oid"]})
        exp["calories"] += p["calories"]; exp["protein_g"] += p["protein_g"]
    # tortilla 290 + rice 70 + chicken 150 + beans 45 + pico 10 = 565 cal; 8+2+19+2+0 = 31 g
    assert exp == {"calories": 565, "protein_g": 31}
    items[2]["price"] = 12.85  # typed: Chipotle Chicken has no receipt price
    r = menus.post("/orders/manual", json={"user_id": 2, "vendor_id": sazon, "items": items}, headers=AUTH)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["macros"]["calories"] == 565 and o["macros"]["protein_g"] == 31
    assert o["subtotal"] == 12.85 and o["points_spent"] == pytest.approx(13.81)  # x 1.075
    # the typed price is remembered and now shows on the menu
    m2 = menus.get(f"/vendors/{sazon}/menu", headers=AUTH).json()
    assert find(m2, "Chipotle Chicken")["known_price"]["price"] == 12.85
    # delete: wrong user 404, right user ok
    assert menus.delete(f"/orders/{o['id']}?user_id=999", headers=AUTH).status_code == 404
    assert menus.delete(f"/orders/{o['id']}?user_id=2", headers=AUTH).json() == {"deleted": o["id"]}


def test_manual_rejects_item_from_another_vendor(menus):
    skillet_item = find(menus.get(f"/vendors/{vid(menus, 'The Skillet')}/menu", headers=AUTH).json(), "Bacon")
    p = skillet_item["portions"][0]
    r = menus.post("/orders/manual", json={"user_id": 2, "vendor_id": vid(menus, "Sazon"),
                   "items": [{"item_oid": skillet_item["item_oid"], "uofm_oid": p["uofm_oid"]}]}, headers=AUTH)
    assert r.status_code == 422


def test_hours_logic():
    ny = ZoneInfo("America/New_York")
    sprout = {"mon": [["08:00", "10:30"], ["11:00", "21:00"]]}
    mon = lambda h, m=0: datetime(2026, 11, 9, h, m, tzinfo=ny)   # a Monday
    assert is_open(sprout, mon(9)) and not is_open(sprout, mon(10, 45)) and is_open(sprout, mon(11))
    assert opens_within(sprout, mon(10, 45), __import__("datetime").timedelta(hours=2)) == mon(11)
    late = {"fri": [["20:00", "02:00"]]}
    assert is_open(late, datetime(2026, 11, 14, 1, tzinfo=ny))  # Sat 1 AM, Friday's shift
