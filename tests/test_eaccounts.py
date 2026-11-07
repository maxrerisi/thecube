from datetime import datetime
from decimal import Decimal as D

import pytest

from dukedining.eaccounts import (
    EAccountsParseError,
    EARow,
    channel_of,
    food_balance,
    group_purchases,
    last4,
    parse_amount,
    parse_any,
    parse_paste,
    row_keys,
    terminal,
)


def test_parse_amount_formats():
    assert parse_amount("(13.81) USD") == D("-13.81")
    assert parse_amount("1,023.00 USD") == D("1023.00")
    assert parse_amount("-4.28") == D("-4.28")
    with pytest.raises(EAccountsParseError):
        parse_amount("lots")


def test_last4_only():
    assert last4("6009 **** **** 1234") == "1234"
    assert last4("1234567890123456") == "3456"
    assert last4("8313") == "8313"


def test_terminal_codes():
    assert terminal("Il Forno ILFReg1") == ("Il Forno", "ILF", "Reg")
    assert terminal("Its Thyme THYKsk1") == ("Its Thyme", "THY", "Ksk")
    assert terminal("Gothic Grill GOTWeb1") == ("Gothic Grill", "GOT", "Web")
    assert terminal("Vending - Coke VC - Aycock") is None


@pytest.mark.parametrize(
    "location, account, amount, channel",
    [
        ("Gothic Grill GOTWeb1", "Food", D("-13.81"), "mobile order"),
        ("Il Forno ILFReg1", "Food", D("-13.81"), "register"),
        ("Its Thyme THYKsk1", "Food", D("-12.78"), "kiosk"),
        ("Vending - Pepsi VP - Southgate", "Food", D("-2.75"), "vending"),
        ("Lobby Shop 7200-28-NET-LS", "Food", D("-2.89"), "convenience store"),
        ("General ePrint ePr-OIT-EastHallLX", "ePrint", D("-0.56"), "print"),
        ("DukeCard Offices DCO TelOfc Manual", "Food", D("1023.00"), "deposit"),
        ("Somewhere Else", "Food", D("-1.00"), "other"),
    ],
)
def test_channel_of(location, account, amount, channel):
    assert channel_of(location, account, amount) == channel


def test_load_csv(ea_rows):
    assert len(ea_rows) == 20
    r = ea_rows[0]
    assert r == EARow(datetime(2026, 9, 13, 15, 0), "Food", "2222", "Farmstead FARReg1", "Debit", D("-10.75"))


def test_paste_tab_separated_matches_csv(fixtures, ea_rows):
    pasted = parse_paste((fixtures / "eaccounts_paste.tsv").read_text())
    assert len(pasted) == 5
    assert pasted[0] == ea_rows[0]
    assert pasted[1].amount == D("0.10") and pasted[1].type == "Credit"
    assert pasted[3].account == "Food - Orientation" and pasted[3].card_last4 == "1111"
    assert pasted[4].amount == D("1500.00")


def test_paste_one_cell_per_line(fixtures):
    tsv = (fixtures / "eaccounts_paste.tsv").read_text()
    one_per_line = "\n".join(c for line in tsv.splitlines() for c in line.split("\t"))
    assert parse_paste(one_per_line) == parse_paste(tsv)


def test_paste_bad_rows_raise():
    with pytest.raises(EAccountsParseError):
        parse_paste("9/13/2026 3:00 PM\tFood\t2222\n")


def test_parse_any_detects_format(fixtures, ea_rows):
    assert parse_any((fixtures / "eaccounts.csv").read_text()) == ea_rows
    assert len(parse_any((fixtures / "eaccounts_paste.tsv").read_text())) == 5


def test_split_across_food_accounts_is_one_purchase(ea_rows):
    groups = group_purchases(ea_rows)
    got = [g for g in groups if g.location == "Gothic Grill GOTWeb1"]
    assert len(got) == 1
    assert got[0].spent == D("10.75")
    assert got[0].accounts == "Food+Food - Orientation"
    assert got[0].n_rows == 2


def test_void_pairs_net_to_zero(ea_rows):
    voids = [g for g in group_purchases(ea_rows) if g.location == "Its Thyme THYKsk1"]
    assert len(voids) == 1 and voids[0].spent == 0 and voids[0].n_rows == 2


def test_groups_sorted_by_time(ea_rows):
    groups = group_purchases(ea_rows)
    assert [g.when for g in groups] == sorted(g.when for g in groups)
    assert len(groups) == 18


def test_food_balance_sums_food_rows_since_first_deposit(ea_rows):
    # the $1.00 vending charge on 8/19 predates the first deposit and is excluded
    spent = sum(-r.amount for r in ea_rows if r.family == "Food" and r.amount < 0 and r.when.day != 19)
    voids_back = D("0.10")
    assert food_balance(ea_rows) == D("525.00") - spent + voids_back


def test_food_balance_none_without_deposit(ea_rows):
    assert food_balance([r for r in ea_rows if r.amount < 0]) is None


def test_row_keys_stable_when_newer_rows_are_prepended(ea_rows):
    old = ea_rows[5:]
    keys_old = row_keys(old)
    keys_new = row_keys(ea_rows)
    assert keys_new[5:] == keys_old
    assert len(set(keys_new)) == len(keys_new)


def test_row_keys_distinguish_identical_rows():
    r = EARow(datetime(2026, 9, 1, 12, 0), "Food", "1111", "Vending - X", "Debit", D("-1.00"))
    keys = row_keys([r, r])
    assert keys[0] != keys[1]
    assert row_keys([r, r]) == keys
