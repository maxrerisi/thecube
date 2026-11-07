from decimal import Decimal as D

import pytest

from dukedining.receipts import (
    ReceiptParseError,
    html_to_text,
    parse_eml,
    parse_pasted_receipt,
    parse_receipts,
)


def test_parses_all_fixture_receipts(receipts):
    assert [r.txn for r in receipts] == [f"90000000{i}" for i in range(1, 9)]


def test_arithmetic_invariant_holds_for_every_receipt(receipts):
    for r in receipts:
        assert r.arithmetic_errors() == [], r.txn


def test_arithmetic_check_catches_mismatch(receipts):
    r = receipts[0]
    r.tax = D("0.99")
    assert any("tax" in e for e in r.arithmetic_errors())


def test_base_price_on_sub_line_and_paid_addon(receipts):
    bowl = receipts[0].items[0]
    assert bowl.name == "Burrito Bowl"
    assert bowl.base == ("Pulled Pork", D("11.50"))
    assert [(a.text, a.price) for a in bowl.addons] == [("Guacamole", D("1.59"))]
    assert "White Rice" in bowl.modifiers and "Pico de Gallo" in bowl.modifiers
    assert bowl.total == D("13.09")


def test_sub_item_vs_modifier_levels(receipts):
    meal = receipts[4].items[0]
    assert [l.level for l in meal.lines] == [0, 1, 1, 1]
    bowl = receipts[0].items[0]
    assert bowl.lines[1].level == 2  # "        White Rice"
    assert bowl.lines[2].level == 1  # "     Pulled Pork"


def test_base_price_on_item_line(receipts):
    assert receipts[1].items[0].base == ("", D("10.00"))


def test_target_address_phone_blank_lines_and_notes(receipts):
    r = receipts[1]
    assert r.location == "Gothic Grill" and r.building == "Bryan Center"
    assert r.target == "1:20 PM"
    assert r.extra_header == ["125 Science Dr, Durham, NC 27708", "(919) 555-0100"]
    assert r.notes == ["Cutlery Needed", "BAG ITEMS - TO-GO"]
    assert r.items[0].modifiers == ["No Onions"]


def test_board_plan_tender(receipts):
    r = receipts[2]
    assert r.board_swipe == D("6.10")
    assert r.food_points == D("4.28")


def test_credit_card_tender(receipts):
    r = receipts[3]
    assert r.tenders == {"Visa": D("8.06")}
    assert r.food_points is None
    assert r.items[1].base == ("Large", D("4.00"))


def test_multiple_items(receipts):
    r = receipts[4]
    assert [(i.number, i.name, i.total) for i in r.items] == [
        (1, "Meal Deal", D("5.80")),
        (2, "Fountain Drink", D("1.99")),
    ]


def test_inline_prices_are_accepted():
    text = """=== #1
2026-09-01 12:00 PM
Cafe
Brodhead Center
1. Bagel $3.50
        Cream Cheese $0.75
Subtotal $4.25
Tax $0.32
Total $4.57
Student Food $4.57
"""
    (r,) = parse_receipts(text)
    assert r.items[0].base == ("", D("3.50"))
    assert r.items[0].addons[0].price == D("0.75")
    assert r.food_points == D("4.57")
    assert r.arithmetic_errors() == []


@pytest.mark.parametrize(
    "body, msg",
    [
        ("Cafe\n1. Bagel\n$1.00\n", "date/time"),
        ("2026-09-01 12:00 PM\nCafe\nSubtotal\n$1.00\n", "no items"),
        ("2026-09-01 12:00 PM\nCafe\n1. Bagel\n$1.00\nSubtotal\n$1.00\n", "missing"),
    ],
)
def test_parse_errors(body, msg):
    with pytest.raises(ReceiptParseError, match=msg):
        parse_receipts("=== #1\n" + body)


def test_html_to_text_one_line_per_cell():
    html = (
        "<table><tr><td>1. Bowl</td><td>$7.99</td></tr></table><style>x{}</style><p>A&nbsp;&amp;&nbsp;B</p>"
    )
    assert html_to_text(html) == "1. Bowl\n$7.99\nA & B"


def test_eml_html_body_falls_back_from_useless_plain_part(fixtures):
    r = parse_eml((fixtures / "receipt_html.eml").read_bytes())
    assert r.txn == "900000009"
    assert r.location == "Ginger & Soy"
    assert r.target == "6:15 PM"
    item = r.items[0]
    assert item.base == ("", D("7.99"))
    assert [(a.text, a.price) for a in item.addons] == [("Chili Oil", D("0.50"))]
    assert item.modifiers == ["Extra Napkins"]
    assert r.food_points == D("9.13")
    assert r.arithmetic_errors() == []


def test_eml_forwarded_as_attachment(fixtures):
    r = parse_eml((fixtures / "receipt_forwarded_attachment.eml").read_bytes())
    assert r.txn == "900000010"
    assert r.items[0].base == ("Oat Milk", D("5.25"))
    assert r.arithmetic_errors() == []


def test_eml_forwarded_inline_with_quoting(fixtures):
    r = parse_eml((fixtures / "receipt_forwarded_inline.eml").read_bytes())
    assert r.txn == "900000011"
    assert r.location == "Farmstead & Sprout Sandwiches"
    assert r.items[0].modifiers == ["Side Salad"]
    assert r.arithmetic_errors() == []


def test_eml_without_receipt_raises():
    data = b"Subject: hello\nContent-Type: text/plain\n\nnothing to see\n"
    with pytest.raises(ReceiptParseError):
        parse_eml(data)


def test_pasted_email_body(fixtures):
    body = (fixtures / "receipt_forwarded_inline.eml").read_text().split("\n\n", 1)[1]
    (r,) = parse_pasted_receipt(body)
    assert r.txn == "900000011"


def test_pasted_transcription_format(fixtures):
    assert len(parse_pasted_receipt((fixtures / "receipts.txt").read_text())) == 8
