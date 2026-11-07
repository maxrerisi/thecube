"""T9 done-when: Halal + Peanut set -> no violating picks. Plus SPEC 10 properties."""
from unittest import mock

import pytest

from app.core import clock, optimizer
from app.db import connect
from conftest import AUTH
from test_import import EMAILS

pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")
TIMES = [(9, 30), (12, 30), (15, 0), (18, 30)]


@pytest.fixture(scope="module")
def demo(menus):
    with mock.patch.dict("os.environ", {"DEMO_TODAY": "2026-11-07"}):
        assert menus.post("/admin/reset-demo", headers=AUTH).status_code == 200
    return menus


def at(h, m):
    return clock.now().replace(year=2026, month=11, day=7, hour=h, minute=m, second=0, microsecond=0)


def run(client, bias, h, m):
    fake = at(h, m)
    with mock.patch.dict("os.environ", {"DEMO_TODAY": "2026-11-07"}), mock.patch.object(clock, "now", lambda: fake):
        r = client.get(f"/next-meal?user_id=2&bias={bias}", headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def item_traits(oids):
    with connect() as conn:
        return {r["item_oid"]: r for r in conn.execute(
            "SELECT item_oid, name, diets, allergens FROM nn_items WHERE item_oid = ANY(%s)", (list(oids),)).fetchall()}


def test_halal_peanut_no_violations(demo):
    s = demo.get("/settings?user_id=2", headers=AUTH).json()
    s.update(require_diets=["halal"], avoid_allergens=["peanut"])
    assert demo.put("/settings?user_id=2", json=s, headers=AUTH).status_code == 200
    try:
        seen = 0
        for bias in ("balanced", "protein", "cheap"):
            for h, m in TIMES:
                r = run(demo, bias, h, m)
                assert r["restrictions"] == {"require_diets": ["halal"], "avoid_allergens": ["peanut"]}
                comps = [c for p in r["picks"] for c in p["components"]]
                traits = item_traits({c["item_oid"] for c in comps})
                for c in comps:
                    t = traits[c["item_oid"]]
                    assert "peanut" not in t["allergens"], t
                    assert "halal" in t["diets"] or "vegan" in t["diets"], t
                seen += len(r["picks"])
        assert seen >= 12  # restrictions still leave real picks
    finally:
        s.update(require_diets=[], avoid_allergens=[])
        demo.put("/settings?user_id=2", json=s, headers=AUTH)


def test_picks_change_with_restrictions_and_bias(demo):
    plain = [p["title"] for p in run(demo, "protein", 12, 30)["picks"]]
    by_bias = {b: [p["title"] for p in run(demo, b, 12, 30)["picks"]] for b in ("balanced", "protein", "cheap")}
    assert len({tuple(v) for v in by_bias.values()}) == 3  # each bias gives a different list
    s = demo.get("/settings?user_id=2", headers=AUTH).json()
    s.update(require_diets=["halal"], avoid_allergens=["peanut"])
    demo.put("/settings?user_id=2", json=s, headers=AUTH)
    try:
        assert [p["title"] for p in run(demo, "protein", 12, 30)["picks"]] != plain
    finally:
        s.update(require_diets=[], avoid_allergens=[])
        demo.put("/settings?user_id=2", json=s, headers=AUTH)


def test_spec10_properties(demo):
    r = run(demo, "balanced", 12, 30)
    picks = r["picks"]
    assert len(picks) == 3 and len({p["vendor_id"] for p in picks}) >= 2
    assert [p["score"] for p in picks] == sorted((p["score"] for p in picks), reverse=True)
    assert r["meals_left"] == 2 and run(demo, "balanced", 18, 30)["meals_left"] == 1
    for p in picks:  # macros are the sum of real components; price from receipts, points = price x 1.075
        assert p["protein_g"] == pytest.approx(sum(c["protein_g"] for c in p["components"]))
        assert p["points_cost"] == pytest.approx(round(p["price"] * 1.075, 2))
        assert p["calories"] >= optimizer.MIN_MEAL_SHARE * r["per_meal_target"]["calories"]
    with connect() as conn:  # every vendor picked was open at 12:30 on a Saturday
        for p in picks:
            from app.core.hours import is_open
            h = conn.execute("SELECT hours FROM vendors WHERE id = %s", (p["vendor_id"],)).fetchone()["hours"]
            assert is_open(h, at(12, 30))


def test_allowed_rule():
    halal_chicken = {"diets": ["halal"], "allergens": []}
    rice = {"diets": ["vegan", "vegetarian"], "allergens": []}
    aioli = {"diets": ["vegetarian"], "allergens": ["egg", "milk", "soy"]}
    pork = {"diets": [], "allergens": []}
    assert optimizer.allowed(halal_chicken, ["halal"], []) and optimizer.allowed(rice, ["halal"], [])
    assert not optimizer.allowed(aioli, ["halal"], []) and not optimizer.allowed(pork, ["halal"], [])
    assert not optimizer.allowed(pork, [], ["peanut"])  # no trait data + any restriction
    assert optimizer.allowed(pork, [], [])
    assert not optimizer.allowed(aioli, [], ["egg"]) and optimizer.allowed(aioli, ["vegetarian"], ["peanut"])
