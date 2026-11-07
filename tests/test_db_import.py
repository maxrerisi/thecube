from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import Date, inspect
from sqlmodel import func, select

from app.models import (
    USER_TABLES,
    ImportBatch,
    Match,
    PurchaseGroup,
    Receipt,
    ReceiptItem,
    SharedCatalogEntry,
    Transaction,
    User,
    UserCatalogEntry,
)
from app.services import ingest, recompute
from app.services.privacy import delete_all_user_data
from dukedining.catalog import build_catalog
from dukedining.eaccounts import load_csv, parse_paste
from dukedining.receipts import parse_receipts


def count(session, model):
    return session.exec(select(func.count()).select_from(model)).one()


def test_import_counts(loaded):
    session, user = loaded
    assert count(session, Receipt) == 8
    assert count(session, ReceiptItem) == 10
    assert count(session, Transaction) == 20
    assert count(session, PurchaseGroup) == 18
    assert count(session, Match) == 18


def test_reimport_is_idempotent(loaded, receipts, ea_rows):
    session, user = loaded
    before = {m.__name__: count(session, m) for m in USER_TABLES if m is not ImportBatch}
    s1 = ingest.import_receipts(session, user, receipts)
    s2 = ingest.import_eaccounts(session, user, ea_rows)
    assert (s1.new, s1.duplicate) == (0, 8)
    assert (s2.new, s2.duplicate) == (0, 20)
    after = {m.__name__: count(session, m) for m in USER_TABLES if m is not ImportBatch}
    assert before == after


def test_paste_overlapping_csv_only_adds_new_rows(loaded, fixtures):
    session, user = loaded
    pasted = parse_paste((fixtures / "eaccounts_paste.tsv").read_text())
    s = ingest.import_eaccounts(session, user, pasted)
    assert (s.new, s.duplicate) == (1, 4)  # only the $1,500 deposit is new


def test_card_numbers_stored_as_last4(session, user, fixtures):
    ingest.import_eaccounts(session, user, parse_paste((fixtures / "eaccounts_paste.tsv").read_text()))
    cards = set(session.exec(select(Transaction.card_last4)).all())
    assert cards == {"1111", "2222"}


def test_split_purchase_completed_by_later_import(session, user, receipts, ea_rows):
    ingest.import_receipts(session, user, receipts)
    half = [r for r in ea_rows if not (r.location == "Gothic Grill GOTWeb1" and r.account == "Food")]
    ingest.import_eaccounts(session, user, half)
    g = session.exec(select(PurchaseGroup).where(PurchaseGroup.location == "Gothic Grill GOTWeb1")).one()
    assert g.spent_cents == 475
    ingest.import_eaccounts(session, user, ea_rows)
    session.refresh(g)
    assert g.spent_cents == 1075 and g.n_rows == 2
    m = session.exec(select(Match).where(Match.group_id == g.id)).one()
    assert m.status == "itemized"


def test_match_statuses(loaded):
    session, user = loaded
    st = recompute.stats(session, user.id)
    assert st.counts == {"itemized": 7, "not_food": 4, "unique": 1, "ambiguous": 2, "unknown": 4}
    assert st.need_review == 3  # Il Forno (ambiguous), Farmstead (ambiguous, other locations), Commons


def test_receipts_roundtrip_through_db(loaded, receipts):
    session, user = loaded
    from_db, ids = recompute.core_receipts(session, user.id)
    assert set(ids) == {r.txn for r in receipts}
    assert build_catalog(from_db).keys() == build_catalog(receipts).keys()
    for a, b in zip(sorted(from_db, key=lambda r: r.txn), receipts, strict=True):
        assert a.tenders == b.tenders and a.arithmetic_errors() == []


def test_user_catalog_built_from_receipts(loaded):
    session, user = loaded
    rows = session.exec(select(UserCatalogEntry).where(UserCatalogEntry.user_id == user.id)).all()
    keys = {(e.location, e.item, e.price_cents, e.kind) for e in rows}
    assert ("Sazon", "+ Guacamole", 159, "addon") in keys
    assert all(e.source == "receipt" for e in rows)


def test_arithmetic_mismatch_is_imported_with_warning(session, user, receipts):
    receipts[0].tax = D("0.99")
    s = ingest.import_receipts(session, user, receipts[:1])
    assert s.new == 1 and s.warnings
    assert session.exec(select(Receipt)).one().arithmetic_ok is False


def test_parse_receipt_inputs_mixed(fixtures):
    files = [
        ("a.eml", (fixtures / "receipt_html.eml").read_bytes()),
        ("b.txt", (fixtures / "receipts.txt").read_bytes()),
        ("bad.eml", b"Subject: hi\n\nnope"),
    ]
    rs, errors = ingest.parse_receipt_inputs(files, (fixtures / "receipts.txt").read_text())
    assert len(rs) == 9  # duplicates across inputs collapse by txn
    assert len(errors) == 1 and errors[0].startswith("bad.eml")


def test_parse_eaccounts_input_errors_are_reported():
    rows, errors = ingest.parse_eaccounts_input("not\ta\ttable")
    assert rows == [] and errors


def test_delete_all_my_data(loaded):
    session, user = loaded
    day = date(2026, 9, 1)
    session.add(SharedCatalogEntry(location="X", item="Y", base_price_cents=1, first_seen=day, last_seen=day))
    session.commit()
    delete_all_user_data(session, user.id)
    for model in (*USER_TABLES, User):
        assert count(session, model) == 0, model.__name__
    assert count(session, SharedCatalogEntry) == 1


def test_shared_catalog_has_no_traceable_columns(session):
    cols = {c["name"]: c["type"] for c in inspect(session.get_bind()).get_columns("sharedcatalogentry")}
    assert set(cols) == {
        "id",
        "location",
        "item",
        "base_price_cents",
        "is_addon",
        "first_seen",
        "last_seen",
        "times_seen",
    }
    assert isinstance(cols["first_seen"], Date) and isinstance(cols["last_seen"], Date)


ROOT = Path(__file__).parent.parent


@pytest.mark.skipif(not (ROOT / "data" / "eaccounts_raw.csv").exists(), reason="real data/ not present")
def test_real_data_through_db(session, user):
    rs = parse_receipts((ROOT / "data" / "receipts_raw.txt").read_text())
    rows = load_csv((ROOT / "data" / "eaccounts_raw.csv").read_text())
    ingest.import_receipts(session, user, rs)
    s = ingest.import_eaccounts(session, user, rows)
    st = recompute.stats(session, user.id)
    assert st.counts["itemized"] == 54
    assert st.counts == {"itemized": 54, "not_food": 32, "unknown": 8, "unique": 5, "ambiguous": 1}
    assert s.need_review == 4
    again = ingest.import_eaccounts(session, user, rows)
    assert again.new == 0 and again.duplicate == 135
