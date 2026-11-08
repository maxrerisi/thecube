"""Wrapped: code computes 8 slides from Blue Devil's term; captions only use each slide's facts."""
import pytest

from app.coach import gemini
from conftest import AUTH
from test_import import EMAILS

pytestmark = pytest.mark.skipif(not EMAILS, reason="emails/ not present")


@pytest.fixture(autouse=True)
def fixed_day(monkeypatch):
    monkeypatch.setenv("DEMO_TODAY", "2026-11-07")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # template captions: deterministic


def test_no_orders_is_404(client):
    assert client.get("/wrapped?user_id=1", headers=AUTH).status_code == 404  # before any reset


def test_wrapped_story(menus):
    assert menus.post("/admin/reset-demo", headers=AUTH).status_code == 200
    w = menus.get("/wrapped?user_id=2", headers=AUTH).json()
    ids = [s["id"] for s in w["slides"]]
    assert ids == ["intro", "totals", "top_spot", "signature", "protein", "peak_hour", "personality", "share"]
    by = {s["id"]: s for s in w["slides"]}
    assert by["totals"]["big"] == "86" and by["intro"]["big"] == "71"
    assert by["personality"]["big"] == "The Sprinter"  # 135 behind pace
    assert all(s["caption"] for s in w["slides"]) and "facts" not in by["intro"]


def test_caption_number_check_is_per_slide():
    data = {"term": "Fall 2026", "slides": [{"id": "totals", "facts": {"meals": 87}},
                                           {"id": "protein", "facts": {"protein_total_g": 2670, "eggs_equivalent": 445}}]}
    assert gemini.check("wrapped", {"captions": ["87 meals!", "445 eggs of protein."]}, data) == []
    assert gemini.check("wrapped", {"captions": ["445 meals!", "445 eggs."]}, data)  # 445 is not a totals fact
    assert gemini.check("wrapped", {"captions": ["87 meals!"]}, data)                 # one caption per slide

