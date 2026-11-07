"""Regression against the real (gitignored) data/ and out/ files. Skipped when absent."""

import csv
import io
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from dukedining import cli
from dukedining.catalog import build_catalog
from dukedining.eaccounts import food_balance, group_purchases, load_csv
from dukedining.matching import AMBIGUOUS, ITEMIZED, OWN, classify, learn_location_aliases
from dukedining.receipts import parse_receipts

ROOT = Path(__file__).parent.parent
RECEIPTS = ROOT / "data" / "receipts_raw.txt"
EACCOUNTS = ROOT / "data" / "eaccounts_raw.csv"
GOLDEN = ROOT / "out"

pytestmark = pytest.mark.skipif(
    not (RECEIPTS.exists() and EACCOUNTS.exists()), reason="real data/ files not present"
)


@pytest.fixture(scope="module")
def real():
    receipts = parse_receipts(RECEIPTS.read_text())
    rows = load_csv(EACCOUNTS.read_text())
    groups = group_purchases(rows)
    alias = learn_location_aliases(groups, receipts)
    pools = [(OWN, list(build_catalog(receipts).values()))]
    matches = [(g, classify(g, receipts, alias, pools)) for g in groups]
    return receipts, rows, matches


def test_receipt_count_and_arithmetic(real):
    receipts, _, _ = real
    assert len(receipts) == 55
    assert [r.txn for r in receipts if r.arithmetic_errors()] == []


def test_mobile_orders_itemized_and_one_unmatched(real):
    receipts, _, matches = real
    itemized = [m for _, m in matches if m.status == ITEMIZED]
    assert len(itemized) == 54
    matched = {m.receipt.txn for m in itemized}
    unmatched = [r for r in receipts if r.txn not in matched]
    assert len(unmatched) == 1
    assert list(unmatched[0].tenders) == ["Amex"]


def test_net_food_equals_balance(real):
    _, rows, _ = real
    assert food_balance(rows) == D("433.24")


def test_oct20_il_forno_has_two_candidates(real):
    _, _, matches = real
    (m,) = [
        m
        for g, m in matches
        if g.location == "Il Forno ILFReg1" and g.when.date() == datetime(2026, 10, 20).date()
    ]
    assert m.status == AMBIGUOUS
    assert len(m.candidates) == 2


@pytest.mark.skipif(not GOLDEN.exists(), reason="prototype out/ not present")
def test_cli_output_identical_to_prototype(tmp_path, capsys):
    cli.main(str(RECEIPTS), str(EACCOUNTS), str(tmp_path))
    for name in ("orders", "order_items", "price_catalog", "transactions_matched"):
        new = (tmp_path / f"{name}.csv").read_text()
        old = (GOLDEN / f"{name}.csv").read_text()
        assert list(csv.reader(io.StringIO(new))) == list(csv.reader(io.StringIO(old))), name
