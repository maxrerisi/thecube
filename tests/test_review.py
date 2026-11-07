from decimal import Decimal as D

import pytest
from sqlmodel import select

from app.models import Match, PurchaseGroup, UserCatalogEntry
from app.services import review


def group_at(session, location):
    return session.exec(select(PurchaseGroup).where(PurchaseGroup.location == location)).one()


def match_of(session, g):
    return session.exec(select(Match).where(Match.group_id == g.id)).one()


def test_queue_contains_uncertain_in_person_charges(loaded):
    session, user = loaded
    locs = [c.group.location for c in review.queue(session, user.id)]
    assert locs == ["Il Forno ILFReg1", "Commons COMReg1", "Farmstead FARReg1"]  # oldest first


def test_pick_candidate_confirms_and_counts_in_catalog(loaded):
    session, user = loaded
    g = group_at(session, "Il Forno ILFReg1")
    m = match_of(session, g)
    idx = next(i for i, c in enumerate(m.candidates) if c[0]["item"] == "Chicken Alfredo")
    review.answer(session, user, g.id, f"c{idx}")
    session.refresh(m)
    assert m.status == "user_confirmed"
    assert [l["item"] for l in m.chosen] == ["Chicken Alfredo"]
    e = session.exec(select(UserCatalogEntry).where(UserCatalogEntry.item == "Chicken Alfredo")).one()
    assert e.times_seen == 2  # one receipt + this answer
    assert g.id not in {c.group.id for c in review.queue(session, user.id)}


def test_something_else_uses_charge_minus_tax_and_resolves_others(loaded, ea_rows):
    session, user = loaded
    # a second Commons charge for the same amount, on another day
    from dataclasses import replace

    from app.services import ingest

    commons = next(r for r in ea_rows if r.location == "Commons COMReg1")
    ingest.import_eaccounts(session, user, [replace(commons, when=commons.when.replace(day=20))])
    assert sum(c.group.location == "Commons COMReg1" for c in review.queue(session, user.id)) == 2

    g = review.queue(session, user.id)[1].group
    res = review.answer(session, user, g.id, "other", other_name="  Pasta   Bar ")
    assert res.also_resolved == 1  # the other $7.77 Commons charge now has a unique match
    e = session.exec(select(UserCatalogEntry).where(UserCatalogEntry.item == "Pasta Bar")).one()
    assert (e.location, e.price_cents, e.source) == ("Commons", 723, "user")  # 7.77 / 1.075
    others = [
        c for c in session.exec(select(PurchaseGroup).where(PurchaseGroup.location == "Commons COMReg1"))
    ]
    statuses = sorted(match_of(session, x).status for x in others)
    assert statuses == ["unique", "user_confirmed"]


def test_something_else_with_explicit_price(loaded):
    session, user = loaded
    g = group_at(session, "Commons COMReg1")
    review.answer(session, user, g.id, "other", other_name="Salad", other_price="$6.50")
    assert match_of(session, g).chosen[0]["price_cents"] == 650


@pytest.mark.parametrize(
    "kwargs, msg",
    [
        ({"choice": "other"}, "what you got"),
        ({"choice": "other", "other_name": "x", "other_price": "abc"}, "Price"),
        ({"choice": "c99"}, "no longer"),
        ({"choice": ""}, "Pick"),
    ],
)
def test_answer_validation(loaded, kwargs, msg):
    session, user = loaded
    g = group_at(session, "Commons COMReg1")
    with pytest.raises(review.ReviewError, match=msg):
        review.answer(session, user, g.id, **kwargs)


def test_skip_moves_to_end(loaded):
    session, user = loaded
    first = review.queue(session, user.id)[0].group
    review.answer(session, user, first.id, "skip")
    assert first.id not in [c.group.id for c in review.queue(session, user.id)]
    assert review.queue(session, user.id, include_skipped=True)[-1].group.id == first.id
    assert review.counts(session, user.id)["skipped"] == 1


def test_unconfirm_returns_to_queue(loaded):
    session, user = loaded
    g = group_at(session, "Commons COMReg1")
    review.answer(session, user, g.id, "other", other_name="Salad")
    review.unconfirm(session, user, g.id)
    assert match_of(session, g).status == "unknown"
    assert not session.exec(select(UserCatalogEntry).where(UserCatalogEntry.item == "Salad")).all()


def test_cannot_review_non_in_person(loaded):
    session, user = loaded
    g = group_at(session, "Sazon SAZWeb1")
    with pytest.raises(review.ReviewError):
        review.answer(session, user, g.id, "skip")


def test_confirmed_answer_survives_reimport(loaded, receipts, ea_rows):
    session, user = loaded
    from app.services import ingest

    g = group_at(session, "Commons COMReg1")
    review.answer(session, user, g.id, "other", other_name="Salad", other_price="7.23")
    ingest.import_eaccounts(session, user, ea_rows)
    ingest.import_receipts(session, user, receipts)
    assert match_of(session, g).status == "user_confirmed"


# ---------------------------------------------------------------- web
def test_review_page_shows_first_card(loaded_client):
    r = loaded_client.get("/review")
    assert r.status_code == 200
    assert "Il Forno" in r.text and "$12.90" in r.text
    assert "Meatballs &amp; Spaghetti" in r.text and "Chicken Alfredo" in r.text
    assert "Something else" in r.text


def test_review_flow_over_htmx(loaded_client):
    c = loaded_client
    with c.db() as s:
        gid = review.queue(s, 1)[0].group.id
    r = c.post(f"/review/{gid}", data={"choice": "c0", "action": "confirm"}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Saved." in r.text
    assert 'id="nav-review-badge" hx-swap-oob="true"' in r.text
    assert "Commons" in r.text  # next card


def test_review_error_keeps_card(loaded_client):
    with loaded_client.db() as s:
        gid = review.queue(s, 1)[1].group.id
    r = loaded_client.post(f"/review/{gid}", data={"choice": "other"}, headers={"HX-Request": "true"})
    assert r.status_code == 422
    assert "Tell us what you got." in r.text


def test_all_caught_up(loaded_client):
    c = loaded_client
    for _ in range(3):
        with c.db() as s:
            gid = review.queue(s, 1)[0].group.id
        c.post(f"/review/{gid}", data={"action": "skip"}, headers={"HX-Request": "true"})
    r = c.get("/review")
    assert "All caught up." in r.text and "You skipped 3" in r.text
    assert "Il Forno" in c.get("/review?skipped=1").text


def test_price_format(loaded):
    session, _ = loaded
    assert review.suggested_price(group_at(session, "Commons COMReg1")) == D("7.23")
