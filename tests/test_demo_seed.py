"""The demo script (DEMO.md) promises specific moments; keep them true."""

from decimal import Decimal as D

import pytest
from sqlmodel import select

from app.models import PurchaseGroup
from app.services import ingest, review, stats
from dukedining.eaccounts import food_balance, parse_paste
from dukedining.receipts import parse_receipts
from scripts import seed_demo


@pytest.fixture(scope="module")
def world():
    w = seed_demo.build()
    seed_demo.check_demo_moments(w)
    return w, *seed_demo.texts(w)


def test_deterministic(world):
    _, seed_receipts, *_ = world
    assert seed_demo.texts(seed_demo.build())[0] == seed_receipts


def test_demo_story(session, user, world):
    _, seed_receipts, seed_tsv, live_tsv, live_orders = world
    receipts = parse_receipts(seed_receipts)
    assert all(r.arithmetic_errors() == [] for r in receipts)
    rows = parse_paste(seed_tsv)
    ingest.import_receipts(session, user, receipts)
    first = ingest.import_eaccounts(session, user, rows, reported_balance=food_balance(rows))
    d = stats.build(session, user.id)
    assert d.reconciled is True
    assert d.run_out is not None and d.run_out < d.term_end  # the "runs out before finals" moment
    assert first.need_review == 3
    queue = [c.group.location for c in review.queue(session, user.id)]
    assert sorted(queue) == ["Bseisu Coffee Bar BSEReg1", "Commons COMReg1", "Il Forno ILFReg1"]

    # live import: the emails plus the full table (overlapping what's already there)
    live = [seed_demo.parse_eml(o.eml()) for o in live_orders if not o.card]
    s1 = ingest.import_receipts(session, user, live)
    live_rows = parse_paste(live_tsv)
    s2 = ingest.import_eaccounts(session, user, live_rows, reported_balance=food_balance(live_rows))
    assert s1.new == len(live) and s2.duplicate == len(rows) and s2.new == len(live_rows) - len(rows)
    assert s2.need_review == 5
    assert stats.build(session, user.id).reconciled is True

    # answering the first Commons charge resolves the second one
    commons = session.exec(
        select(PurchaseGroup).where(PurchaseGroup.location == "Commons COMReg1").order_by(PurchaseGroup.when)
    ).all()
    res = review.answer(session, user, commons[0].id, "other", other_name="Pasta Bar")
    assert res.also_resolved == 1
    assert review.suggested_price(commons[0]) == D("8.48")

    # picking Chicken Alfredo (option 2) moves it to the top for the next Il Forno charge
    il_forno = [c for c in review.queue(session, user.id) if c.group.location == "Il Forno ILFReg1"]
    first = [c[0]["item"] for c in il_forno[0].match.candidates]
    assert first == ["Meatballs & Spaghetti", "Chicken Alfredo"]
    review.answer(session, user, il_forno[0].group.id, "c1")
    nxt = [c for c in review.queue(session, user.id) if c.group.location == "Il Forno ILFReg1"]
    assert nxt[0].match.candidates[0][0]["item"] == "Chicken Alfredo"
