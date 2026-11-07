"""Command-line report (the original prototype's output, unchanged).

Usage:
    python -m dukedining data/receipts_raw.txt data/eaccounts_raw.csv out/
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

from .catalog import ADDON, ITEM, build_catalog, by_location
from .eaccounts import group_purchases, load_csv
from .matching import OTHER_LOCATIONS, OWN, classify, describe, learn_location_aliases
from .money import CENT, TAX_RATE, with_tax
from .receipts import BOARD_PLAN, STUDENT_FOOD, parse_receipts


def status_text(m, p) -> tuple[str, str, str, str]:
    """(status, receipt_txn, what_you_got, other_candidates) in the prototype's wording."""
    txn = got = alts = ""
    pretax = (p.spent / (1 + TAX_RATE)).quantize(CENT)
    d = m.detail
    if d == "void":
        status = "voided (debit/credit pair cancels)"
    elif d == "deposit":
        status = "deposit"
    elif d == "print":
        status = "print job"
    elif d == "itemized":
        r = m.receipt
        status, txn = "itemized (receipt)", r.txn
        got = "; ".join(f"{it.name}" + (f" ({it.base[0]})" if it.base[0] else "") for it in r.items)
        if BOARD_PLAN in r.tenders:
            got += f"  [board swipe covered ${r.tenders[BOARD_PLAN]}]"
    elif d == "swipe_remainder":
        status = "board-swipe remainder or retry (no receipt)"
    elif d == "receipt_missing":
        status = "mobile order, receipt missing"
    elif d == "in_person":
        cands = m.candidates
        suffix = f" ({OTHER_LOCATIONS})" if m.scope == OTHER_LOCATIONS else ""
        if not cands:
            status = f"in person - no catalog match (~${pretax} before tax)"
        elif len(cands) == 1:
            status = "in person - unique match" + suffix
            got = describe(cands[0])
        else:
            status = f"in person - {len(cands)} possible matches, pick one" + suffix
            got = describe(cands[0])
            alts = " | ".join(describe(c) for c in cands[1:8])
    else:
        status = f"{p.channel} - not itemizable (~${pretax} before tax)"
    return status, txn, got, alts


def main(receipts_path: str, eacct_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    receipts = parse_receipts(Path(receipts_path).read_text())
    catalog = build_catalog(receipts)
    rows = load_csv(Path(eacct_path).read_text())
    groups = group_purchases(rows)
    alias = learn_location_aliases(groups, receipts)
    by_loc = by_location(catalog.values())
    pools = [(OWN, list(catalog.values()))]

    with open(out / "orders.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "receipt_txn",
                "datetime",
                "location",
                "building",
                "subtotal",
                "tax",
                "total",
                "food_points",
                "board_plan_equivalency",
                "other_payment",
                "items",
            ]
        )
        for r in receipts:
            w.writerow(
                [
                    r.txn,
                    r.when.isoformat(sep=" "),
                    r.location,
                    r.building,
                    r.subtotal,
                    r.tax,
                    r.total,
                    r.tenders.get(STUDENT_FOOD, ""),
                    r.tenders.get(BOARD_PLAN, ""),
                    "; ".join(f"{k} {v}" for k, v in r.other_tenders.items()),
                    "; ".join(it.name for it in r.items),
                ]
            )
    with open(out / "order_items.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "receipt_txn",
                "datetime",
                "location",
                "line",
                "item",
                "option",
                "base_price",
                "paid_addons",
                "line_total",
                "modifiers",
            ]
        )
        for r in receipts:
            for it in r.items:
                label, price = it.base
                w.writerow(
                    [
                        r.txn,
                        r.when.isoformat(sep=" "),
                        r.location,
                        it.number,
                        it.name,
                        label,
                        price,
                        "; ".join(f"{a.text} {a.price}" for a in it.addons),
                        it.total,
                        "; ".join(it.modifiers),
                    ]
                )

    with open(out / "price_catalog.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "location",
                "kind",
                "item",
                "price",
                "price_with_tax",
                "options_seen",
                "times_ordered",
                "last_ordered",
            ]
        )
        for e in sorted(catalog.values(), key=lambda e: (e.location, e.kind, e.item, e.price)):
            w.writerow(
                [
                    e.location,
                    e.kind,
                    e.item,
                    e.price,
                    with_tax(e.price),
                    "; ".join(sorted(e.variants)),
                    e.times,
                    e.last.date().isoformat(),
                ]
            )

    stats: dict[str, int] = defaultdict(int)
    matched_receipts = set()
    with open(out / "transactions_matched.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "datetime",
                "location",
                "channel",
                "accounts",
                "card_last4",
                "spent",
                "status",
                "receipt_txn",
                "what_you_got",
                "other_candidates",
            ]
        )
        for g in groups:
            m = classify(g, receipts, alias, pools)
            if m.receipt:
                matched_receipts.add(m.receipt.txn)
            status, txn, got, alts = status_text(m, g)
            head = status.split(",")[0] if status.startswith("in person") else status
            key = head.split(" (")[0]
            stats[key] += 1
            w.writerow(
                [
                    g.when.strftime("%Y-%m-%d %H:%M"),
                    g.location,
                    g.channel,
                    g.accounts,
                    g.card_last4,
                    g.spent,
                    status,
                    txn,
                    got,
                    alts,
                ]
            )

    unmatched = [r for r in receipts if r.txn not in matched_receipts]
    print(f"receipts parsed: {len(receipts)}   eAccounts rows: {len(rows)}   purchase groups: {len(groups)}")
    print(
        f"catalog: {sum(1 for e in catalog.values() if e.kind == ITEM)} items, "
        f"{sum(1 for e in catalog.values() if e.kind == ADDON)} add-ons, {len(by_loc)} locations"
    )
    print("location aliases learned:", alias)
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {v:3d}  {k}")
    print(
        "receipts with no eAccounts match:",
        [(r.txn, r.location, str(r.total), list(r.tenders)) for r in unmatched],
    )


if __name__ == "__main__":
    main(*sys.argv[1:4])
