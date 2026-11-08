"""T8 done-when: two resets identical, including after demo-style changes in between."""
from datetime import date

import pytest

from app import demo
from app.db import connect
from conftest import AUTH
from test_import import EMAILS

pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setenv("DEMO_TODAY", "2026-11-07")


def test_two_resets_identical_and_story(menus):
    r1 = menus.post("/admin/reset-demo", headers=AUTH).json()
    assert r1["price_receipts"] == 31 and r1["warnings"] == []

    # what a live demo does: log a meal, toggle Halal + Peanut, type a price, enter a balance
    sazon = next(v["id"] for v in menus.get("/vendors", headers=AUTH).json() if v["name"] == "Sazon")
    item = menus.get(f"/vendors/{sazon}/menu", headers=AUTH).json()["courses"][0]["items"][0]
    menus.post("/orders/manual", headers=AUTH, json={"user_id": 2, "vendor_id": sazon, "items": [
        {"item_oid": item["item_oid"], "uofm_oid": item["portions"][0]["uofm_oid"], "price": 3.0}]})
    s = menus.get("/settings?user_id=2", headers=AUTH).json()
    s.update(require_diets=["halal"], avoid_allergens=["peanut"])
    menus.put("/settings?user_id=2", json=s, headers=AUTH)
    menus.post("/balance", json={"user_id": 2, "points": 321.0, "swipes": 3}, headers=AUTH)

    r2 = menus.post("/admin/reset-demo", headers=AUTH).json()
    assert r2["fingerprint"] == r1["fingerprint"]
    r3 = menus.post("/admin/reset-demo", headers=AUTH).json()
    assert r3["fingerprint"] == r1["fingerprint"]

    # SPEC 14 story for Blue Devil: Plan A, behind pace, short on protein
    t = menus.get("/today?user_id=2", headers=AUTH).json()
    assert t["user"]["name"] == "Blue Devil"
    assert t["targets"] == {"calories": 2800, "protein_g": 150}
    assert len(t["meals"]) == 1 and 20 <= t["eaten"]["protein_g"] <= 40          # ~28 g so far today (breakfast)
    p = t["points"]
    assert p["meal_plan"] == "A" and p["pace_target"] == 974.54                    # even Plan A pace, Nov 7
    assert p["vs_pace"] == -135.0                                                  # 135 behind pace
    assert p["runout"] == "2026-12-09"                                             # first day of finals
    assert p["on_pace"] is False
    assert t["protein_hit_days_7"] <= 2                                             # short most weekdays
    assert menus.get("/settings?user_id=2", headers=AUTH).json()["require_diets"] == []
    with connect() as conn:  # every Blue Devil component is a real NetNutrition item; prices from receipts
        n = conn.execute("""SELECT count(*) AS n FROM order_components c JOIN order_items oi ON oi.id = c.order_item_id
                            JOIN orders o ON o.id = oi.order_id JOIN users u ON u.id = o.user_id
                            WHERE u.name = 'Blue Devil' AND c.item_oid IS NULL""").fetchone()["n"]
        assert n == 0


def test_one_account_and_receipts_are_only_prices(menus):
    """The app has one account; the real receipts teach prices but leave no orders behind."""
    menus.post("/admin/reset-demo", headers=AUTH)
    assert [u["name"] for u in menus.get("/users", headers=AUTH).json()] == ["Blue Devil"]
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM orders WHERE source = 'email'").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM prices WHERE source = 'receipt'").fetchone()["n"] > 20
