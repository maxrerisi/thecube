from decimal import Decimal as D

from dukedining.money import money, pretax_candidates, pretax_for, receipt_tax, tax_on, with_tax


def test_money_parses_commas_and_dollars():
    assert money("1,023.00") == D("1023.00")
    assert money("$4.5") == D("4.50")


def test_tax_rounds_half_up_not_bankers():
    # 3.00 * 0.075 = 0.225 -> half-up 0.23 (banker's rounding would give 0.22)
    assert tax_on(D("3.00")) == D("0.23")
    assert tax_on(D("12.85")) == D("0.96")


def test_with_tax():
    assert with_tax(D("12.85")) == D("13.81")
    assert with_tax(D("1.99")) == D("2.14")


def test_board_swipe_only_taxes_amount_above_swipe():
    # Skillet $10.08 with a $6.10 swipe: tax on $3.98 is $0.30, $4.28 charged to Food Points
    tax = receipt_tax(D("10.08"), D("6.10"))
    assert tax == D("0.30")
    assert D("10.08") + tax - D("6.10") == D("4.28")
    # swipe covers nearly everything: 0.09 taxable -> 0.00675 -> 0.01
    assert receipt_tax(D("11.89"), D("11.80")) == D("0.01")
    # swipe bigger than subtotal never produces negative tax
    assert receipt_tax(D("5.00"), D("6.10")) == D("0.00")


def test_pretax_candidates_inverts_with_tax():
    for cents in range(1, 3000, 7):
        s = D(cents) / 100
        assert s in pretax_candidates(with_tax(s))
    assert pretax_candidates(D("0")) == []


def test_pretax_for_always_reproduces_charge_when_possible():
    assert pretax_for(D("13.81")) == D("12.85")
    for cents in range(1, 2000):
        charged = D(cents) / 100
        p = pretax_for(charged)
        if pretax_candidates(charged):
            assert with_tax(p) == charged
