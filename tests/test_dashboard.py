from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlmodel import func, select

from app.models import Receipt, Transaction
from app.services import ingest, stats
from dukedining.eaccounts import load_csv
from dukedining.receipts import parse_receipts


def test_empty_dashboard(session, user):
    assert stats.build(session, user.id).has_data is False


def test_balance_computed_without_reported(loaded):
    session, user = loaded
    d = stats.build(session, user.id)
    assert d.balance_source == "computed" and d.reconciled is None
    assert d.balance_cents == 525_00 - (
        1407 + 1075 + 428 + 837 + 1290 + 1290 + 10 + 1290 + 1075 + 777 + 1075 + 250 + 386
    )


def test_reconciliation_check(loaded):
    session, user = loaded
    computed = stats.build(session, user.id).computed_cents
    ingest.import_eaccounts(session, user, [], reported_balance=D(computed) / 100)
    d = stats.build(session, user.id)
    assert d.reconciled is True and d.balance_source == "eAccounts"
    ingest.import_eaccounts(session, user, [], reported_balance=D("1.00"))
    assert stats.build(session, user.id).reconciled is False


def test_spend_breakdowns(loaded):
    session, user = loaded
    d = stats.build(session, user.id)
    assert d.n_purchases == 14  # food purchases with money spent (voids, deposits, prints excluded)
    places = dict(d.by_location)
    assert places["Il Forno"] == 1290 * 3
    assert d.by_location[0] == ("Il Forno", 1290 * 3)
    assert len(d.by_location) == 9 and d.by_location[-1][0] == "Everywhere else"
    assert sum(places.values()) == d.spent_cents
    assert sum(c for _, c in d.by_week) == d.spent_cents
    assert d.by_week[0][0] == date(2026, 8, 17)  # Monday of the first deposit's week
    assert d.swipes == 2 and d.swipe_value_cents == 610 + 1180
    top = {e["item"]: e for e in d.top_items}
    assert top["Smash Burger"]["count"] == 2  # receipt + unique in-person match


def test_projection(loaded, monkeypatch):
    session, user = loaded
    monkeypatch.setenv("DUKEDINING_TERM_END", "2026-12-18")
    d = stats.build(session, user.id)
    assert d.weekly_cents > 0 and d.run_out is not None
    assert d.left_at_term_end_cents is not None


def test_dashboard_page(loaded_client):
    r = loaded_client.get("/")
    assert r.status_code == 200
    assert "Food balance" in r.text and "weekChart" in r.text and "Top items" in r.text


def test_empty_dashboard_page(client):
    assert "Start with an import" in client.get("/").text


def test_purchases_page_filters(loaded_client):
    food = loaded_client.get("/purchases").text
    assert "Burrito Bowl" in food and "Deposit" not in food
    assert "Deposit" in loaded_client.get("/purchases?show=all").text
    review = loaded_client.get("/purchases?show=review").text
    assert "Commons" in review and "Burrito Bowl" not in review


def test_catalog_page(loaded_client):
    r = loaded_client.get("/catalog").text
    assert "Burrito Bowl" in r and "+ Guacamole" in r and "Community catalog" in r


def test_delete_requires_confirmation_then_deletes(loaded_client):
    r = loaded_client.post("/privacy/delete", data={"confirm": "nope"}, follow_redirects=False)
    assert r.headers["location"] == "/privacy?error=1"
    r = loaded_client.post("/privacy/delete", data={"confirm": "delete"})
    assert "All your data was deleted." in r.text
    with loaded_client.db() as s:
        assert s.exec(select(func.count()).select_from(Transaction)).one() == 0
        assert s.exec(select(func.count()).select_from(Receipt)).one() == 0


ROOT = Path(__file__).parent.parent


@pytest.mark.skipif(not (ROOT / "data" / "eaccounts_raw.csv").exists(), reason="real data/ not present")
def test_real_data_reconciles(session, user):
    ingest.import_receipts(session, user, parse_receipts((ROOT / "data" / "receipts_raw.txt").read_text()))
    rows = load_csv((ROOT / "data" / "eaccounts_raw.csv").read_text())
    ingest.import_eaccounts(session, user, rows, reported_balance=D("433.24"))
    d = stats.build(session, user.id)
    assert d.reconciled is True and d.balance_cents == 43324
