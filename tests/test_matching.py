import random
from datetime import timedelta
from decimal import Decimal as D
from itertools import combinations_with_replacement

import pytest

from dukedining.catalog import ADDON, ITEM, CatalogEntry, build_catalog
from dukedining.eaccounts import group_purchases
from dukedining.matching import (
    AMBIGUOUS,
    HERE,
    ITEMIZED,
    NOT_FOOD,
    OTHER_LOCATIONS,
    OWN,
    SHARED,
    UNIQUE,
    UNKNOWN,
    candidates,
    classify,
    find_receipt,
    in_person_candidates,
    learn_location_aliases,
)
from dukedining.money import with_tax


@pytest.fixture
def world(receipts, ea_rows):
    groups = group_purchases(ea_rows)
    catalog = build_catalog(receipts)
    alias = learn_location_aliases(groups, receipts)
    pools = [(OWN, list(catalog.values()))]

    def at(location):
        (g,) = [g for g in groups if g.location == location]
        return g, classify(g, receipts, alias, pools)

    return groups, catalog, alias, pools, at


def test_catalog_learns_items_and_addons(receipts):
    cat = build_catalog(receipts)
    bowl = cat[("Sazon", "Burrito Bowl", D("11.50"), ITEM)]
    assert bowl.variants == {"Pulled Pork"} and bowl.times == 1
    assert ("Sazon", "+ Guacamole", D("1.59"), ADDON) in cat
    # paid credit-card receipts still teach prices
    assert ("Cafe", "Bagel", D("3.50"), ITEM) in cat


def test_mobile_order_matches_on_time_and_student_food_amount(world, receipts):
    groups, *_ = world
    g = next(g for g in groups if g.location == "Sazon SAZWeb1")
    assert find_receipt(g, receipts).txn == "900000001"
    g.when += timedelta(minutes=2)  # 3 minutes after the receipt: outside the window
    assert find_receipt(g, receipts) is None


def test_mobile_order_amount_must_equal_student_food(world, receipts):
    groups, *_ = world
    g = next(g for g in groups if g.location == "Sazon SAZWeb1")
    g.spent += D("0.01")
    assert find_receipt(g, receipts) is None


def test_split_account_order_matches_receipt(world):
    *_, at = world
    _, m = at("Gothic Grill GOTWeb1")
    assert m.status == ITEMIZED and m.receipt.txn == "900000002"


def test_ten_cent_web_charge_with_receipt_is_a_real_order(world):
    *_, at = world
    g, m = at("Its Thyme THYWeb1")
    assert g.spent == D("0.10")
    assert m.status == ITEMIZED and m.receipt.board_swipe == D("11.80")


def test_board_swipe_order_matches_on_food_points_part(world):
    *_, at = world
    assert at("Skillet SKIWeb1")[1].receipt.txn == "900000003"


def test_location_aliases_learned_from_mobile_orders(world):
    _, _, alias, *_ = world
    assert alias["ILF"] == "Il Forno"
    assert alias["SKI"] == "The Skillet"
    assert alias["MCD"] == "McDonald's"
    assert "FAR" not in alias and "COM" not in alias


def test_voids_deposits_prints_are_not_food(world):
    groups, _, alias, pools, _ = world
    by_detail = {}
    for g in groups:
        m = classify(g, [], alias, pools)
        by_detail.setdefault(m.detail, set()).add(m.status)
    assert by_detail["void"] == {NOT_FOOD}
    assert by_detail["deposit"] == {NOT_FOOD}
    assert by_detail["print"] == {NOT_FOOD}


def test_in_person_ambiguous(world):
    *_, at = world
    _, m = at("Il Forno ILFReg1")
    assert m.status == AMBIGUOUS and m.scope == HERE and m.source == OWN
    assert sorted(c[0].item for c in m.candidates) == ["Chicken Alfredo", "Meatballs & Spaghetti"]


def test_in_person_unique(world):
    *_, at = world
    _, m = at("Gothic Grill GOTReg1")
    assert m.status == UNIQUE
    assert [e.item for e in m.candidates[0]] == ["Smash Burger"]


def test_in_person_unknown_location_falls_back_to_all_locations(world):
    *_, at = world
    _, m = at("Farmstead FARReg1")
    assert m.scope == OTHER_LOCATIONS
    assert m.location == "Farmstead"
    assert [e.item for e in m.candidates[0]] == ["Smash Burger"]  # fewest lines first
    assert [e.item for e in m.candidates[1]] == ["Meal Deal", "Meal Deal"]
    assert m.status == AMBIGUOUS


def test_in_person_no_match(world):
    *_, at = world
    _, m = at("Commons COMReg1")
    assert m.status == UNKNOWN and m.candidates == []


def test_vending_and_lobby_shop_not_itemizable(world):
    *_, at = world
    assert at("Vending - Coke VC - Aycock")[1].detail == "not_itemizable"
    assert at("Lobby Shop 7200-28-NET-LS")[1].status == UNKNOWN


def entry(loc, name, price, kind=ITEM, times=1):
    return CatalogEntry(loc, name, D(price), kind=kind, times=times)


def test_addons_only_alongside_an_item():
    pool = [entry("X", "+ Guac", "1.59", ADDON), entry("X", "Bowl", "10.00")]
    assert candidates(with_tax(D("1.59")), pool) == []
    assert candidates(with_tax(D("3.18")), pool) == []
    (combo,) = candidates(with_tax(D("11.59")), pool)
    assert {e.item for e in combo} == {"Bowl", "+ Guac"}


def test_ranking_fewest_lines_then_most_ordered():
    pool = [
        entry("X", "A", "5.00", times=1),
        entry("X", "B", "10.00", times=1),
        entry("X", "C", "10.00", times=9),
    ]
    combos = candidates(with_tax(D("10.00")), pool)
    assert [[e.item for e in c] for c in combos] == [["C"], ["B"], ["A", "A"]]


def test_own_catalog_before_shared():
    own = [entry("X", "Mine", "10.00")]
    shared = [entry("X", "Theirs", "10.00"), entry("X", "Theirs too", "10.00")]
    c, source, scope = in_person_candidates(with_tax(D("10.00")), "X", [(OWN, own), (SHARED, shared)])
    assert source == OWN and scope == HERE and [e.item for e in c[0]] == ["Mine"]
    c, source, scope = in_person_candidates(with_tax(D("10.00")), "X", [(OWN, []), (SHARED, shared)])
    assert source == SHARED and len(c) == 2


def _brute_force(amount, entries, max_items=3):
    """The prototype's original O(n^k) enumeration, kept as the reference implementation."""
    found = []
    for k in range(1, max_items + 1):
        for combo in combinations_with_replacement(entries, k):
            if all(e.kind == ADDON for e in combo):
                continue
            if with_tax(sum((e.price for e in combo), D("0"))) == amount:
                found.append(list(combo))
    found.sort(key=lambda c: (len(c), -sum(e.times for e in c)))
    return found


@pytest.mark.parametrize("seed", range(25))
def test_fast_candidates_equal_brute_force(seed):
    rng = random.Random(seed)
    prices = [D(rng.randrange(50, 1500, 25)) / 100 for _ in range(rng.randrange(3, 14))]
    pool = [
        entry("X", f"i{i}", str(p), ADDON if rng.random() < 0.25 else ITEM, rng.randrange(1, 5))
        for i, p in enumerate(prices)
    ]
    for _ in range(15):
        k = rng.randrange(1, 4)
        amount = with_tax(sum((rng.choice(pool).price for _ in range(k)), D("0")))
        for max_items in (2, 3):
            fast = [[id(e) for e in c] for c in candidates(amount, pool, max_items)]
            slow = [[id(e) for e in c] for c in _brute_force(amount, pool, max_items)]
            assert fast == slow
