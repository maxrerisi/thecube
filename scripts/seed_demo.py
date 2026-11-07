"""Load a realistic, fully SYNTHETIC semester into the app for public demos.

    uv run python scripts/seed_demo.py            # reset dukedining.db and seed it
    uv run python scripts/seed_demo.py --db sqlite:///other.db

Generates a made-up student's Aug 15 - Nov 6 2026 history (invented items, prices, times,
card numbers), runs it through the real parsers and import pipeline, and writes:

    demo/seed/receipts.txt, demo/seed/eaccounts_table.tsv   what gets pre-loaded (through Nov 1)
    demo/live/*.eml, demo/live/eaccounts_table.tsv         what you import live during the demo

Deterministic: same output every run.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from email.message import EmailMessage
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dukedining.catalog import build_catalog  # noqa: E402
from dukedining.eaccounts import food_balance, parse_paste  # noqa: E402
from dukedining.matching import candidates  # noqa: E402
from dukedining.money import receipt_tax, with_tax  # noqa: E402
from dukedining.receipts import parse_eml, parse_receipts  # noqa: E402

DEMO_DIR = ROOT / "demo"
START, LIVE_FROM, END = date(2026, 8, 15), date(2026, 11, 2), date(2026, 11, 6)
MOBILE_CARD = "6012 **** **** 4821"  # mobile orders
WALLET_CARD = "6012 **** **** 7390"  # Apple Wallet taps in person
DEPOSIT, ORIENTATION = D("1150.00"), D("40.00")

# Invented menu: (item, base price, option label carrying the price or "", add-ons, modifiers)
B, BC = "Brodhead Center", "Bryan Center"
VENUES = {
    "Sazon": ("SAZ", B, [("Burrito Bowl", "11.85", "Grilled Chicken", [("Guacamole", "1.75")], ["Cilantro Rice", "Black Beans", "Pico de Gallo"]),
                         ("Quesadilla", "11.85", "", [], ["Fajita Peppers", "Sour Cream"])]),
    "Il Forno": ("ILF", B, [("Chicken Alfredo", "12.45", "", [], ["Garlic Knot"]),
                            ("Meatballs & Spaghetti", "12.45", "", [], ["Garlic Knot"]),
                            ("Margherita Flatbread", "10.95", "", [], [])]),
    "Gothic Grill": ("GOT", BC, [("Smash Burger", "10.95", "", [], ["No Pickles"]),
                                 ("Chicken Tender Basket", "11.25", "", [], ["Honey Mustard"]),
                                 ("Turkey Club Wrap", "12.25", "", [], ["Sweet Potato Fries"])]),
    "McDonald's": ("MCD", BC, [("Meal Deal", "5.00", "McChicken", [("Large Fountain Drink", "0.80")], ["Small Fry"]),
                               ("Fountain Drink", "1.99", "Medium Fountain Drink", [], [])]),
    "Its Thyme": ("THY", BC, [("Acai Bowl", "11.89", "", [], ["Granola", "Banana"]),
                              ("Thai Peanut Bowl", "12.39", "", [], [])]),
    "Ginger & Soy": ("GIN", B, [("Pork Dumplings", "7.99", "", [], []),
                                ("Teriyaki Chicken Bowl", "11.49", "", [], ["Brown Rice"])]),
    "Beyu Blue": ("BYB", BC, [("Latte", "4.75", "Medium", [("Oat Milk", "0.70")], []),
                              ("Cold Brew", "4.25", "", [], [])]),
    "The Skillet": ("SKI", B, [("Breakfast Plate", "10.08", "", [], ["Scrambled Eggs", "Bacon"])]),
    "Farmstead & Sprout Sandwiches": ("SPR", B, [("Honey Garlic Chicken", "12.75", "", [], []),
                                                 ("Caprese Panini", "11.25", "", [], [])]),
}  # fmt: skip
EACCOUNTS_NAME = {
    "The Skillet": "Skillet",
    "McDonald's": "McDonalds",
    "Farmstead & Sprout Sandwiches": "Sprout",
}


@dataclass
class Order:
    when: datetime
    venue: str
    picks: list[tuple]  # (item tuple, with_addons)
    txn: str = ""
    swipe: D | None = None
    card: str | None = None  # credit card brand line if paid by card

    @property
    def subtotal(self) -> D:
        return sum((D(i[1]) + (sum(D(a[1]) for a in i[3]) if add else 0) for i, add in self.picks), D("0"))

    @property
    def tax(self) -> D:
        return receipt_tax(self.subtotal, self.swipe or D("0"))

    @property
    def total(self) -> D:
        return self.subtotal + self.tax

    @property
    def food(self) -> D:
        return self.total - (self.swipe or 0)

    def lines(self) -> list[tuple[int, str, D | None]]:
        """(indent, text, price) in receipt order."""
        out = []
        for n, (item, add) in enumerate(self.picks, 1):
            name, price, option, addons, mods = item
            if option:
                out += [(0, f"{n}. {name}", None), (5, option, D(price))]
            else:
                out.append((0, f"{n}. {name}", D(price)))
            out += [(8, m, None) for m in mods]
            if add:
                out += [(8, a, D(p)) for a, p in addons]
        return out

    def receipt_text(self) -> str:
        code, building, _ = VENUES[self.venue]
        t = [
            f"=== #{self.txn}",
            self.when.strftime("%Y-%m-%d %I:%M %p").replace(" 0", " "),
            self.venue,
            building,
        ]
        for indent, text, price in self.lines():
            t.append(" " * indent + text)
            if price is not None:
                t.append(f"${price}")
        t += ["Subtotal", f"${self.subtotal}", "Tax", f"${self.tax}", "Total", f"${self.total}"]
        if self.card:
            t += [self.card, f"${self.total}"]
        else:
            t.append("DukeCard")
            if self.swipe:
                t += [f"Board Plan Equivalency ${self.swipe}", f"1 Used - ${self.swipe}"]
            t += ["Student Food", f"${self.food}"]
        return "\n".join(t) + "\n"

    def eml(self) -> bytes:
        _, building, _ = VENUES[self.venue]
        cell = "<tr><td>{}</td><td>{}</td></tr>"
        rows = [cell.format(self.when.strftime("%Y-%m-%d %I:%M %p").replace(" 0", " "), ""),
                cell.format(f"<b>{escape(self.venue)}</b>", ""), cell.format(building, "")]  # fmt: skip
        for indent, text, price in self.lines():
            rows.append(
                cell.format("&nbsp;" * indent + escape(text), f"${price}" if price is not None else "")
            )
        rows += [cell.format(k, f"${v}") for k, v in (("Subtotal", self.subtotal), ("Tax", self.tax),
                                                      ("Total", self.total))]  # fmt: skip
        rows += [cell.format("DukeCard", ""), cell.format("Student Food", f"${self.food}")]
        html = (f"<html><body><p>Hi Jordan,</p><p>Thanks for ordering with Transact Mobile Ordering!</p>"
                f"<table>{''.join(rows)}</table><p>Powered by Transact</p></body></html>")  # fmt: skip
        msg = EmailMessage()
        msg["From"] = "Transact Mobile Ordering <mobileorder@transactcampus.com>"
        msg["To"] = "jordan.demo@example.edu"
        msg["Subject"] = f"#{self.txn} Receipt"
        msg["Date"] = self.when.strftime("%a, %d %b %Y %H:%M:%S -0500")
        msg.set_content("This receipt is best viewed in an HTML-capable email client.")
        msg.add_alternative(html, subtype="html")
        return bytes(msg)


@dataclass
class Row:
    when: datetime
    account: str
    card: str
    location: str
    type: str
    amount: D  # signed

    def tsv(self) -> str:
        amt = f"({-self.amount:,.2f}) USD" if self.amount < 0 else f"{self.amount:,.2f} USD"
        when = f"{self.when.month}/{self.when.day}/{self.when.year} " + self.when.strftime("%I:%M %p").lstrip(
            "0"
        )
        return "\t".join([when, self.account, self.card, self.location, self.type, amt])


@dataclass
class World:
    rng: random.Random = field(default_factory=lambda: random.Random(2026))
    orders: list[Order] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    orientation_left: D = ORIENTATION
    next_txn: int = 141_200_000

    def at(self, day: date, h: int, m: int) -> datetime:
        return datetime(day.year, day.month, day.day, h, m)

    def charge(self, when, location, amount, card=WALLET_CARD):
        """Debit Food Points, drawing on the orientation money first (which splits a purchase)."""
        take = min(self.orientation_left, amount)
        if take > 0:
            self.orientation_left -= take
            self.rows.append(Row(when, "Food - Orientation", card, location, "Debit", -take))
        if amount - take > 0:
            self.rows.append(Row(when, "Food", card, location, "Debit", -(amount - take)))

    def mobile(self, when, venue, picks, swipe=None, card=None):
        self.next_txn += self.rng.randrange(20_000, 90_000)
        o = Order(when, venue, picks, str(self.next_txn), swipe, card)
        self.orders.append(o)
        if not card:
            code = VENUES[venue][0]
            name = EACCOUNTS_NAME.get(venue, venue)
            self.charge(
                when + timedelta(minutes=self.rng.choice([0, 1])), f"{name} {code}Web1", o.food, MOBILE_CARD
            )
        return o

    def in_person(self, when, location, pretax: D):
        self.charge(when, location, with_tax(pretax))

    def pick(self, venue, n=1):
        items = VENUES[venue][2]
        return [(self.rng.choice(items), self.rng.random() < 0.3) for _ in range(n)]


def build() -> World:
    w = World()
    r = w.rng
    w.rows.append(
        Row(w.at(START, 11, 39), "Food", MOBILE_CARD, "DukeCard Offices DCO TelOfc Manual", "Credit", DEPOSIT)
    )
    w.rows.append(Row(w.at(START, 15, 2), "Food - Orientation", MOBILE_CARD, "DukeCard Offices Cust Srvc Man 4",
                      "Credit", ORIENTATION))  # fmt: skip
    lunch_spots = ["Sazon", "Gothic Grill", "Il Forno", "Its Thyme", "Farmstead & Sprout Sandwiches",
                   "Ginger & Soy", "McDonald's"]  # fmt: skip
    day = START + timedelta(days=2)
    while day <= END:
        wd = day.weekday() < 5
        if r.random() < (0.75 if wd else 0.35):  # lunch, mobile order
            v = r.choice(lunch_spots)
            w.mobile(w.at(day, r.randrange(11, 14), r.randrange(0, 60)), v, w.pick(v))
        if wd and r.random() < 0.35:  # coffee
            if r.random() < 0.6:
                w.mobile(w.at(day, r.randrange(8, 10), r.randrange(0, 60)), "Beyu Blue", w.pick("Beyu Blue"))
            else:
                w.in_person(w.at(day, 9, r.randrange(0, 60)), "Beyu Blue BYBReg1", D("4.25"))
        if r.random() < 0.18:  # in-person dinner
            spot = r.choice([("Gothic Grill GOTReg1", "10.95"), ("Its Thyme THYKsk1", "11.89"),
                             ("Sazon SAZReg1", "11.85")])  # fmt: skip
            w.in_person(w.at(day, r.randrange(17, 20), r.randrange(0, 60)), spot[0], D(spot[1]))
        if r.random() < 0.06:
            w.charge(
                w.at(day, r.randrange(14, 23), r.randrange(0, 60)), "Vending - Coke VC - Aycock", D("2.50")
            )
        if r.random() < 0.05:
            w.charge(w.at(day, r.randrange(15, 22), r.randrange(0, 60)), "Lobby Shop 7200-28-NET-LS",
                     D(r.choice(["3.86", "2.89", "5.41"])))  # fmt: skip
        if wd and r.random() < 0.12:
            when = w.at(day, r.randrange(10, 22), r.randrange(0, 60))
            for cents in r.sample([16, 32, 48, 56], 2):
                w.rows.append(Row(when, "ePrint", WALLET_CARD, "General ePrint ePr-OIT-PerkinsLX", "Debit",
                                  -D(cents) / 100))  # fmt: skip
        day += timedelta(days=1)

    # Scripted moments the demo relies on
    thyme = VENUES["Its Thyme"][2][0]
    skillet = VENUES["The Skillet"][2][0]
    w.mobile(
        w.at(date(2026, 9, 30), 18, 36), "Its Thyme", [(thyme, False)], swipe=D("11.80")
    )  # $0.10 web charge
    w.mobile(w.at(date(2026, 10, 14), 9, 5), "The Skillet", [(skillet, False)], swipe=D("6.10"))  # $4.28
    w.mobile(w.at(date(2026, 10, 9), 8, 40), "Beyu Blue", w.pick("Beyu Blue"), card="Amex ****1009")
    for d, h, m in [(date(2026, 9, 22), 11, 8), (date(2026, 10, 27), 18, 2)]:  # kiosk swipe retries
        w.rows += [Row(w.at(d, h, m), "Food", WALLET_CARD, "Its Thyme THYKsk1", "Debit", D("-0.10")),
                   Row(w.at(d, h, m), "Food", WALLET_CARD, "Its Thyme THYKsk1", "Credit", D("0.10"))]  # fmt: skip
    w.in_person(w.at(date(2026, 10, 20), 15, 8), "Il Forno ILFReg1", D("12.45"))  # Alfredo or Meatballs?
    w.in_person(w.at(date(2026, 10, 7), 21, 2), "Commons COMReg1", D("8.48"))  # nothing known: "Pasta Bar"
    w.in_person(w.at(date(2026, 9, 8), 15, 3), "Farmstead FARReg1", D("12.75"))  # matched via other places
    w.in_person(w.at(date(2026, 10, 6), 11, 15), "Bseisu Coffee Bar BSEReg1", D("5.35"))
    # live-import week
    w.in_person(w.at(date(2026, 11, 4), 20, 41), "Commons COMReg1", D("8.48"))  # resolved by the first answer
    w.in_person(w.at(date(2026, 11, 5), 12, 30), "Il Forno ILFReg1", D("12.45"))
    return w


def check_demo_moments(w: World) -> None:
    """The demo script promises specific outcomes; fail loudly if the generator drifts."""
    cat = list(build_catalog(parse_receipts("".join(o.receipt_text() for o in w.orders))).values())
    assert len(candidates(with_tax(D("12.45")), [e for e in cat if e.location == "Il Forno"])) == 2
    assert candidates(with_tax(D("8.48")), cat, max_items=2) == [], "Commons charge must start unmatched"
    assert all(not o.receipt_text().count("$-") for o in w.orders)


def texts(w: World) -> tuple[str, str, str, list[Order]]:
    """(seed receipts, seed eAccounts table, live eAccounts table, live orders)."""
    seed_orders = sorted((o for o in w.orders if o.when.date() < LIVE_FROM), key=lambda o: o.when)
    live_orders = [o for o in w.orders if o.when.date() >= LIVE_FROM]
    header = "Date/Time\tAccount Name\tCard Number\tLocation\tTransaction Type\tAmount"
    rows = sorted(w.rows, key=lambda r: r.when, reverse=True)  # eAccounts shows newest first
    seed_rows = [r for r in rows if r.when.date() < LIVE_FROM]
    seed_receipts = "# Synthetic demo data (invented).\n" + "".join(o.receipt_text() for o in seed_orders)
    seed_tsv = "\n".join([header] + [r.tsv() for r in seed_rows]) + "\n"
    live_tsv = (
        "\n".join([header] + [r.tsv() for r in rows]) + "\n"
    )  # full table: overlaps the seed on purpose
    return seed_receipts, seed_tsv, live_tsv, live_orders


def write_files(w: World) -> tuple[str, str, str, list[Order], D]:
    seed_receipts, seed_tsv, live_tsv, live_orders = texts(w)

    (DEMO_DIR / "seed").mkdir(parents=True, exist_ok=True)
    live_dir = DEMO_DIR / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    for f in live_dir.glob("*.eml"):
        f.unlink()
    (DEMO_DIR / "seed" / "receipts.txt").write_text(seed_receipts)
    (DEMO_DIR / "seed" / "eaccounts_table.tsv").write_text(seed_tsv)
    (live_dir / "eaccounts_table.tsv").write_text(live_tsv)
    for o in live_orders:
        if not o.card:
            slug = o.venue.split()[0].lower().replace("'", "")
            (live_dir / f"{o.when:%m%d}-{slug}-{o.txn}.eml").write_bytes(o.eml())
    balance = food_balance(parse_paste(live_tsv))
    return seed_receipts, seed_tsv, live_tsv, live_orders, balance


def seed_db(url: str, seed_receipts: str, seed_tsv: str) -> None:
    from sqlmodel import Session

    from app.db import make_engine
    from app.services import ingest
    from app.services.users import current_user

    if url.startswith("sqlite:///") and not url.startswith("sqlite:////:memory"):
        path = Path(url.removeprefix("sqlite:///"))
        path = path if path.is_absolute() else ROOT / path
        path.unlink(missing_ok=True)
    engine = make_engine(url)
    with Session(engine) as s:
        user = current_user(s)
        user.name = "Jordan (demo)"
        s.commit()
        ingest.import_receipts(s, user, parse_receipts(seed_receipts))
        rows = parse_paste(seed_tsv)
        r = ingest.import_eaccounts(s, user, rows, reported_balance=food_balance(rows))
        print(f"seeded {url}: {len(parse_receipts(seed_receipts))} receipts, {len(rows)} transactions, "
              f"{r.need_review} to review")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="sqlite:///dukedining.db")
    ap.add_argument("--files-only", action="store_true", help="only (re)write demo/ files")
    args = ap.parse_args()
    w = build()
    check_demo_moments(w)
    seed_receipts, seed_tsv, _, live_orders, balance = write_files(w)
    for f in sorted((DEMO_DIR / "live").glob("*.eml")):
        parse_eml(f.read_bytes())  # every live email must parse
    print(f"wrote demo/ ({len(live_orders)} live receipts); balance after live import: {balance}")
    if not args.files_only:
        seed_db(args.db, seed_receipts, seed_tsv)


if __name__ == "__main__":
    main()
