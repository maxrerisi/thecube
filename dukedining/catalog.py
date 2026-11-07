"""Price catalog: (location, item, price, item|addon) lines learned from receipts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .receipts import Receipt

ITEM, ADDON = "item", "addon"


@dataclass
class CatalogEntry:
    location: str
    item: str
    price: Decimal
    variants: set[str] = field(default_factory=set)
    kind: str = ITEM  # "item" or "addon"
    times: int = 0
    last: datetime | None = None
    first: datetime | None = None
    source: str = "receipt"  # where the line came from: receipt / user / shared

    @property
    def key(self) -> tuple:
        return (self.location, self.item, self.price, self.kind)


def build_catalog(receipts: list[Receipt]) -> dict[tuple, CatalogEntry]:
    cat: dict[tuple, CatalogEntry] = {}

    def add(loc, name, price, variant, kind, when):
        key = (loc, name, price, kind)
        e = cat.setdefault(key, CatalogEntry(loc, name, price, kind=kind))
        if variant:
            e.variants.add(variant)
        e.times += 1
        e.last = max(e.last or when, when)
        e.first = min(e.first or when, when)

    for r in receipts:
        for it in r.items:
            if not it.priced:
                continue
            label, price = it.base
            add(r.location, it.name, price, label, ITEM, r.when)
            for a in it.addons:
                add(r.location, f"+ {a.text}", a.price, it.name, ADDON, r.when)
    return cat


def by_location(entries) -> dict[str, list[CatalogEntry]]:
    out: dict[str, list[CatalogEntry]] = defaultdict(list)
    for e in entries:
        out[e.location].append(e)
    return out
