"""T5 done-when: unit tests on sample numbers (SPEC 8), plus /today and /balance via the API."""
from datetime import date, datetime, timedelta

import pytest

from app.core.budget import compute
from app.core.clock import NY

TODAY = date(2026, 11, 7)
END = date(2026, 12, 27)  # 50 days left


def at(d, hour=12, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=NY)


def order(d, pts, swipes=0, hour=12, minute=0):
    return {"ts": at(d, hour, minute), "points_spent": pts, "swipes_used": swipes}


SNAP = {"ts": at(TODAY - timedelta(days=10)), "points": 1000.0, "swipes": 20}


def test_points_daily_budget_and_overspending_runout():
    week = [order(TODAY - timedelta(days=i), 30.0) for i in range(1, 8)]          # 210 over 7 days
    s = compute(SNAP, week + [order(TODAY, 12.5, swipes=1)], END, TODAY)
    assert s.points == pytest.approx(1000 - 210 - 12.5)                             # 777.5
    assert s.swipes == 19
    assert s.days_left == 50
    assert s.daily_budget == pytest.approx(777.5 / 50)                             # 15.55
    assert s.spent_today == 12.5
    assert s.trailing_daily == pytest.approx(30.0)
    assert s.runout == TODAY + timedelta(days=25)                                   # floor(777.5/30)
    assert s.on_pace is False


def test_on_pace_lasts_past_semester_end():
    week = [order(TODAY - timedelta(days=i), 10.0) for i in range(1, 8)]
    s = compute(SNAP, week, END, TODAY)
    assert s.points == 930 and s.trailing_daily == pytest.approx(10.0)
    assert s.runout is None                       # floor(930/10)=93 days > semester end
    assert s.on_pace is True                      # 10 <= 930/50 = 18.6


def test_no_spending_and_no_swipe_balance():
    s = compute({**SNAP, "swipes": None}, [], END, TODAY)
    assert (s.points, s.swipes, s.trailing_daily, s.runout, s.on_pace) == (1000, None, 0, None, True)


def test_orders_before_snapshot_not_subtracted_but_count_toward_trailing():
    snap = {"ts": at(TODAY - timedelta(days=1), 20), "points": 500.0, "swipes": 5}
    s = compute(snap, [order(TODAY - timedelta(days=1), 70.0, hour=9)], END, TODAY)
    assert s.points == 500 and s.trailing_daily == pytest.approx(10.0)


def test_local_day_boundary_and_days_left_floor():
    late = order(TODAY - timedelta(days=1), 9.0, hour=23, minute=30)   # 04:30 UTC "today"
    s = compute(SNAP, [late], date(2026, 11, 1), TODAY)                 # semester already over
    assert s.spent_today == 0 and s.days_left == 1


def test_breaks_skip_days_left_and_runout():
    from app.core.term import add_dining_days, dining_days
    brk = frozenset(date(2026, 11, 25) + timedelta(days=i) for i in range(5))  # Thanksgiving
    week = [order(TODAY - timedelta(days=i), 30.0) for i in range(1, 8)]
    s = compute(SNAP, week, date(2026, 12, 14), TODAY, brk)
    assert s.days_left == 37 - 5                                              # Nov 7..Dec 13 minus 5
    assert s.runout == add_dining_days(TODAY, 26, brk) == date(2026, 12, 8)  # floor(790/30)=26, skips 25-29
    assert dining_days(TODAY, date(2026, 11, 30), brk) == 18


def test_no_snapshot():
    s = compute(None, [order(TODAY, 5.0)], END, TODAY)
    assert s.points is None and s.daily_budget is None and s.spent_today == 5.0


# ---- API ----

def test_today_and_balance_api(client, monkeypatch):
    from conftest import AUTH
    from test_import import EMAILS, post_all
    if not EMAILS:
        pytest.skip("emails/ not present")
    from app.db import connect
    import json
    from pathlib import Path
    from app.ingest import netnutrition
    from app.seed import seed_vendors
    nn = Path(__file__).resolve().parents[2] / "spikes" / "nn.json"
    with connect() as conn:
        netnutrition.write_db(conn, json.loads(nn.read_text()))
        seed_vendors(conn)
    assert post_all(client, 2).json()["imported"] == 31
    monkeypatch.setenv("DEMO_TODAY", "2026-09-08")   # William: Sazon order 125089644, 3:06 PM
    assert client.get("/today?user_id=2").status_code == 401
    r = client.post("/balance", json={"user_id": 2, "points": 400.0, "swipes": 10}, headers=AUTH)
    assert r.status_code == 200
    t = client.get("/today?user_id=2", headers=AUTH).json()
    assert t["date"] == "2026-09-08"
    assert [m["vendor"] for m in t["meals"]] == ["Sazon"]
    assert t["eaten"]["protein_g"] > 0 and t["meals"][0]["items"] == ["Arepa Bowl"]
    assert t["points"]["spent_today"] == pytest.approx(13.81)
    assert t["coach"]["headline"] and t["coach"]["source"] in ("template", "gemini", "cache")
    assert t["points"]["points"] is None  # the only snapshot is stamped now (Nov), after the demo day
    with connect() as conn:  # a snapshot the morning of: today's $13.81 comes off it
        conn.execute("INSERT INTO balance_snapshots VALUES (2, '2026-09-08 08:00-04', 500, 12)")
    p = client.get("/today?user_id=2", headers=AUTH).json()["points"]
    assert (p["points"], p["swipes"]) == (pytest.approx(486.19), 12)
    s = client.get("/settings?user_id=2", headers=AUTH).json()
    s["show_calories"] = False
    assert client.put("/settings?user_id=2", json=s, headers=AUTH).status_code == 200
    t2 = client.get("/today?user_id=2", headers=AUTH).json()
    assert t2["eaten"]["calories"] is None and t2["targets"]["calories"] is None
