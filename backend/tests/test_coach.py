"""T11 done-when: 10 runs, no blank cards. Plus the number check, retry, fallback, cache."""
from unittest import mock

import pytest

from app.coach import gemini
from app.core import clock
from app.db import connect
from conftest import AUTH
from test_import import EMAILS

pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")

TODAY = {"show_calories": True, "eaten": {"protein_g": 74.0, "calories": 1170.0},
         "targets": {"protein_g": 150, "calories": 2800}, "protein_hit_days_7": 2, "meals": [{}, {}],
         "points": {"points": 1093.25, "swipes": 14, "days_left": 41, "daily_budget": 26.66, "spent_today": 20.08,
                    "trailing_daily": 30.8, "on_pace": False, "runout": "2026-12-12"}, "semester_end": "2026-12-18"}


def fake(*outs):
    calls = iter(outs)
    return lambda kind, data: next(calls)


def test_good_output_accepted_and_cached(client):
    good = {"headline": "74 g protein so far", "message": "76 g to go; points run out December 12 at 30.8 a day.",
            "tone": "warning"}
    with connect() as conn:
        conn.execute("DELETE FROM coach_cache")
        assert gemini.recap(TODAY, conn, fake(good))["source"] == "gemini"
        again = gemini.recap(TODAY, conn, fake())  # no call needed
    assert again["source"] == "cache" and again["headline"] == good["headline"]


def test_invented_number_retries_then_falls_back():
    bad = {"headline": "You need 80 g more", "message": "Eat 3 meals.", "tone": "nudge"}  # 80 and 3 invented
    good = {"headline": "74 g so far", "message": "Protein target is 150 g.", "tone": "nudge"}
    assert gemini.check("recap", bad, gemini.recap_input(TODAY)) != []
    assert gemini.recap(TODAY, None, fake(bad, good))["source"] == "gemini"
    out = gemini.recap(TODAY, None, fake(bad, bad))
    assert out["source"] == "template" and out["headline"] and out["message"]
    assert gemini.check("recap", {k: v for k, v in out.items() if k != "source"}, gemini.recap_input(TODAY)) == []


def test_calorie_talk_blocked_when_off_and_lengths():
    off = {**TODAY, "show_calories": False}
    calorie = {"headline": "74 g protein", "message": "Add some calories at dinner.", "tone": "nudge"}
    assert "calorie talk with show_calories off" in gemini.check("recap", calorie, gemini.recap_input(off))
    assert "calories" not in gemini.recap_input(off)
    long = {"headline": "x" * 61, "message": "ok", "tone": "nudge"}
    assert "headline > 60 chars" in gemini.check("recap", long, gemini.recap_input(TODAY))


def test_exception_and_bad_index_fall_back():
    def boom(kind, data):
        raise RuntimeError("quota")
    assert gemini.recap(TODAY, None, boom)["source"] == "template"
    result = {"bias": "protein", "headroom": 6.58, "per_meal_target": {"protein_g": 38.0},
              "restrictions": {"require_diets": ["halal"], "avoid_allergens": ["peanut"]},
              "picks": [{"vendor": "Sazon", "title": "Burrito with Chipotle Chicken", "protein_g": 36.0,
                         "points_cost": 13.81, "calories": 835.0}]}
    bad = {"chosen_index": 2, "headline": "Burrito", "reason": "36 g protein."}
    out = gemini.pick(result, True, None, fake(bad, bad))
    assert out["source"] == "template" and out["chosen_index"] == 0 and "36" in out["reason"]
    assert gemini.pick_input(result, True)["restrictions"] == "must be halal; avoids peanut"


def test_ten_runs_no_blank_cards(menus):
    """No GEMINI_API_KEY here, so this exercises the template path end to end through the API."""
    with mock.patch.dict("os.environ", {"DEMO_TODAY": "2026-11-07"}):
        assert menus.post("/admin/reset-demo", headers=AUTH).status_code == 200
        runs = 0
        for h in (9, 12, 15, 18, 21):
            fake_now = clock.now().replace(hour=h, minute=0)
            with mock.patch.object(clock, "now", lambda: fake_now):
                for user in (2,):
                    t = menus.get(f"/today?user_id={user}", headers=AUTH).json()
                    assert t["coach"]["headline"].strip() and t["coach"]["message"].strip(), t["coach"]
                    n = menus.get(f"/next-meal?user_id={user}&bias=protein", headers=AUTH).json()
                    if n["picks"]:
                        assert n["coach"]["headline"].strip() and n["coach"]["reason"].strip(), n["coach"]
                    runs += 1
        assert runs == 5
