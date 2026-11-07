from decimal import Decimal as D

from sqlmodel import select

from app.models import Match, PurchaseGroup, SharedCatalogEntry, User
from app.services import ingest, shared
from app.services.privacy import delete_all_user_data


def shared_rows(session):
    return {
        (e.location, e.item, e.base_price_cents, e.is_addon): e
        for e in session.exec(select(SharedCatalogEntry))
    }


def test_nothing_shared_without_opt_in(loaded):
    session, _ = loaded
    assert shared_rows(session) == {}


def test_opt_in_contributes_once(session, user, receipts):
    user.share_catalog = True
    ingest.import_receipts(session, user, receipts)
    rows = shared_rows(session)
    assert rows[("Il Forno", "Meatballs & Spaghetti", 1200, False)].times_seen == 1
    assert rows[("Sazon", "+ Guacamole", 159, True)].times_seen == 1
    ingest.import_receipts(session, user, receipts)  # re-import: no double counting
    assert shared.contribute_pending(session, user) == 0
    assert shared_rows(session)[("Il Forno", "Meatballs & Spaghetti", 1200, False)].times_seen == 1


def test_opting_in_later_shares_earlier_receipts(session, user, receipts):
    ingest.import_receipts(session, user, receipts)
    assert shared_rows(session) == {}
    user.share_catalog = True
    assert shared.contribute_pending(session, user) > 0
    e = shared_rows(session)[("Gothic Grill", "Smash Burger", 1000, False)]
    assert (str(e.first_seen), str(e.last_seen)) == ("2026-09-02", "2026-09-02")


def test_other_user_matches_from_shared_catalog(session, user, receipts, ea_rows):
    user.share_catalog = True
    ingest.import_receipts(session, user, receipts)

    other = User(name="Someone else")
    session.add(other)
    session.commit()
    il_forno = [r for r in ea_rows if r.location == "Il Forno ILFReg1"]
    ingest.import_eaccounts(session, other, il_forno)
    g = session.exec(select(PurchaseGroup).where(PurchaseGroup.user_id == other.id)).one()
    m = session.exec(select(Match).where(Match.group_id == g.id)).one()
    assert m.status == "ambiguous" and m.source == "shared"
    assert {c[0]["item"] for c in m.candidates} == {"Meatballs & Spaghetti", "Chicken Alfredo"}
    assert all(c[0]["source"] == "shared" for c in m.candidates)


def test_own_catalog_wins_over_shared(session, user, receipts, ea_rows):
    other = User(name="Someone else", share_catalog=True)
    session.add(other)
    session.commit()
    ingest.import_receipts(session, other, receipts)  # shared now knows Il Forno
    ingest.import_receipts(session, user, receipts)
    ingest.import_eaccounts(session, user, ea_rows)
    g = session.exec(
        select(PurchaseGroup).where(
            PurchaseGroup.user_id == user.id, PurchaseGroup.location == "Il Forno ILFReg1"
        )
    ).one()
    assert session.exec(select(Match).where(Match.group_id == g.id)).one().source == "own"


def test_delete_all_keeps_anonymous_shared_rows(session, user, receipts):
    user.share_catalog = True
    ingest.import_receipts(session, user, receipts)
    n = len(shared_rows(session))
    delete_all_user_data(session, user.id)
    assert len(shared_rows(session)) == n


def test_upload_checkbox_opts_in_and_out(client, fixtures):
    body = (fixtures / "receipts.txt").read_text()
    client.post("/upload", data={"receipt_text": body, "share": "true"})
    with client.db() as s:
        assert s.exec(select(User)).one().share_catalog is True
        assert len(shared_rows(s)) > 0
    assert 'name="share" value="true" checked' in client.get("/upload").text
    client.post("/upload", data={"receipt_text": body})
    with client.db() as s:
        assert s.exec(select(User)).one().share_catalog is False


def test_shared_prices_are_receipt_verified(session, user, receipts):
    user.share_catalog = True
    ingest.import_receipts(session, user, receipts)
    prices = {e.base_price_cents for e in shared_rows(session).values()}
    assert D("12.00") * 100 in prices
