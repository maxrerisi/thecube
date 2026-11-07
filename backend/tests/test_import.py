"""T3 done-when: all 31 import; re-import = 31 duplicates; parsed points match receipts.

"Match receipts" is checked against spikes/parse_receipt.py, the original stdlib parser,
as an independent reference (not the code under test).
"""
import importlib.util
import json
from pathlib import Path

import pytest

from app.db import connect
from app.ingest import netnutrition
from app.seed import seed_vendors
from conftest import AUTH

ROOT = Path(__file__).resolve().parents[2]
EMAILS = sorted((ROOT / "emails").glob("*.eml"))
NN_JSON = ROOT / "spikes" / "nn.json"
pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")


def reference_parser():
    spec = importlib.util.spec_from_file_location("spike_parse_receipt", ROOT / "spikes" / "parse_receipt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.parse


@pytest.fixture(scope="module")
def loaded(client):  # client resets the test DB and seeds users
    with connect() as conn:
        if NN_JSON.exists():
            netnutrition.write_db(conn, json.loads(NN_JSON.read_text()))
        assert seed_vendors(conn) == []
        william = conn.execute("SELECT id FROM users WHERE name = 'William'").fetchone()["id"]
    return client, william


def post_all(client, user_id):
    files = [("files", (p.name, p.read_bytes(), "message/rfc822")) for p in EMAILS]
    return client.post("/import/eml", data={"user_id": user_id}, files=files, headers=AUTH)


def test_import_needs_token(loaded):
    client, william = loaded
    r = client.post("/import/eml", data={"user_id": william},
                    files=[("files", ("a.eml", EMAILS[0].read_bytes(), "message/rfc822"))])
    assert r.status_code == 401


def test_all_31_import_then_31_duplicates(loaded):
    client, william = loaded
    first = post_all(client, william)
    assert first.status_code == 200, first.text
    body = first.json()
    print("\nfirst import:", {k: (v if k != "unknown_components" else len(v)) for k, v in body.items()})
    assert body["imported"] == 31 and body["duplicates"] == 0

    again = post_all(client, william).json()
    print("re-import:   ", {k: (v if k != "unknown_components" else len(v)) for k, v in again.items()})
    assert again == {"imported": 0, "duplicates": 31, "partial": [], "unknown_components": []}


def test_points_match_receipts(loaded):
    parse = reference_parser()
    with connect() as conn:
        orders = {o["external_ref"]: o for o in conn.execute(
            "SELECT external_ref, points_spent, swipes_used, swipe_value, subtotal, tax, total FROM orders").fetchall()}
    assert len(orders) == 31
    total_points = 0.0
    for p in EMAILS:
        ref = parse(p)
        o = orders[ref["order_number"]]
        food = sum(t["amount"] for t in ref["tenders"] if t["account"] == "Student Food")
        swipes = [t for t in ref["tenders"] if t["account"] == "board_plan_swipe"]
        assert float(o["points_spent"]) == pytest.approx(food), p.name
        assert o["swipes_used"] == len(swipes), p.name
        assert float(o["swipe_value"]) == pytest.approx(sum(t["amount"] for t in swipes)), p.name
        assert (float(o["subtotal"]), float(o["tax"]), float(o["total"])) == \
            pytest.approx((ref["subtotal"], ref["tax"], ref["total"])), p.name
        total_points += food
    with connect() as conn:
        db_points = float(conn.execute("SELECT sum(points_spent) AS s FROM orders").fetchone()["s"])
    print(f"\npoints: receipts ${total_points:.2f} == db ${db_points:.2f}")
    assert db_points == pytest.approx(total_points)


def test_prices_and_components(loaded):
    with connect() as conn:
        hh = conn.execute("""SELECT price FROM prices p JOIN vendors v ON v.id = p.vendor_id
                             WHERE v.name = 'Sazon' AND item_name = 'Arepa Bowl' AND variant = 'Hot Honey Chicken'""").fetchone()
        assert float(hh["price"]) == 12.85
        # a simple item with no components gets one component row pointing at itself
        row = conn.execute("""SELECT c.raw_name, i.name FROM order_components c JOIN order_items oi ON oi.id = c.order_item_id
                              JOIN nn_items i ON i.item_oid = c.item_oid WHERE oi.name = 'Vanilla Greek Yogurt Cup'""").fetchone()
        assert (row["raw_name"], row["name"]) == ("Vanilla Greek Yogurt Cup", "Greek Vanilla Yogurt")
        # format portion: burrito components get the burrito portion
        p = conn.execute("""SELECT np.portion_name FROM order_components c JOIN order_items oi ON oi.id = c.order_item_id
                            JOIN nn_portions np ON np.item_oid = c.item_oid AND np.uofm_oid = c.uofm_oid
                            WHERE oi.format = 'burrito' AND c.raw_name = 'Black Beans'""").fetchone()
        assert p["portion_name"] == "Burrito Portion"
        # vendors with no NetNutrition unit are partial
        n = conn.execute("""SELECT count(*) AS n FROM orders o JOIN vendors v ON v.id = o.vendor_id
                            WHERE v.unit_oid IS NULL AND NOT o.macros_partial""").fetchone()["n"]
        assert n == 0


def test_tightened_fuzzy_rules(loaded):
    from app.ingest import matcher
    with connect() as conn:
        aliases = {r["raw"]: r["name"] for r in conn.execute(
            "SELECT a.raw, i.name FROM item_aliases a JOIN nn_items i USING (item_oid)").fetchall()}
        # word-subset tie and sub-90 near miss are NOT auto-aliased (they were under WRatio/80)
        assert "whole" not in aliases and "sweet potato chips" not in aliases
        # clear fuzzy hits still are (not in the seed; matched at >= 90 with no tie)
        assert aliases["fajita peppers and onion"] == "Fajita Peppers and Onions"
        assert aliases["fresh jalapenos"] == "Fresh Jalapeno"
        # vendor fuzzy: clear winner matches but is not persisted; unknown vendor -> None
        n = conn.execute("SELECT count(*) AS n FROM vendor_aliases").fetchone()["n"]
        assert matcher.resolve_vendor(conn, "Devil's Krafthouse")["name"] == "The Devil's Krafthouse"
        assert matcher.resolve_vendor(conn, "Burger King") is None
        assert conn.execute("SELECT count(*) AS n FROM vendor_aliases").fetchone()["n"] == n
