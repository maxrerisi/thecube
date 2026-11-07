"""T2: NetNutrition parsing against cached HTML (no network) + DB upsert."""
import json

import pytest

from app.db import connect
from app.ingest import netnutrition as nn

UNIT18 = sorted(nn.CACHE.glob("unit_18_*.json"))
pytestmark = pytest.mark.skipif(not UNIT18, reason="no cached Sazon panel in spikes/nn_cache")


def sazon_items():
    return nn.parse_items(nn.panels(UNIT18[-1].read_text())["itemPanel"])


def test_sazon_items_and_traits():
    items = sazon_items()
    assert len(items) == 46
    cc = next(i for i in items if i["name"] == "Chipotle Chicken")
    assert cc["course"] == "Choose Protein" and cc["diets"] == ["halal"]
    assert [p["name"] for p in cc["portions"]] == [
        "Taco Portion", "Arepa Bowl Portion", "Quesadilla Portion", "Burrito Portion"]
    assert [p["default"] for p in cc["portions"]] == [True, False, False, False]
    brownie = next(i for i in items if i["name"] == "Brownie with Icing")
    assert brownie["portions"] == [{"uofm_oid": 0, "name": "Brownie", "default": True}]
    assert brownie["allergens"] == ["egg", "gluten", "milk", "soy", "wheat"]


def test_label_per_portion():
    cc = next(i for i in sazon_items() if i["name"] == "Chipotle Chicken")
    taco = nn.parse_label((nn.CACHE / f"{cc['item_oid']}_3061330.html").read_text())
    burrito = nn.parse_label((nn.CACHE / f"{cc['item_oid']}_8244579.html").read_text())
    assert (taco["serving"], taco["grams"], taco["calories"], taco["protein_g"]) == ("Taco Portion", 142, 220, 29)
    assert (burrito["serving"], burrito["calories"], burrito["protein_g"]) == ("Burrito Portion", 150, 19)
    assert taco["fiber_g"] == 0.5 and burrito["fiber_g"] is None  # "< 1g" and "NA"


def test_dining_menu_list():
    html = ("<header class='card-title h4'>Saturday, November 7, 2026</header>"
            "<a onclick=\"javascript:NetNutrition.UI.menuListSelectMenu(9517377);\">Brunch</a>"
            "<a onclick=\"javascript:NetNutrition.UI.menuListSelectMenu(9517378);\">Dinner</a>")
    import datetime as dt
    assert nn.parse_menu_list(html) == [(dt.date(2026, 11, 7), "Brunch", 9517377),
                                        (dt.date(2026, 11, 7), "Dinner", 9517378)]


def test_write_db_upserts(client):  # client fixture resets the test DB
    items = sazon_items()
    sc = nn.Scraper()
    sc.fill_labels(items, (18, None))  # all cached: no network
    assert sc.requests == 0
    data = {"units": [{"unit_oid": 18, "name": "Sazon", "kind": "retail", "items": items}]}
    with connect() as conn:
        assert nn.write_db(conn, data) == {"units": 1, "items": 46, "portions": 119}
        nn.write_db(conn, data)  # idempotent
        row = conn.execute("""SELECT p.calories, p.protein_g FROM nn_portions p JOIN nn_items i USING (item_oid)
                              WHERE i.name = 'Chipotle Chicken' AND p.portion_name = 'Burrito Portion'""").fetchone()
        n = conn.execute("SELECT count(*) AS n FROM nn_portions").fetchone()["n"]
    assert (row["calories"], row["protein_g"]) == (150, 19) and n == 119
