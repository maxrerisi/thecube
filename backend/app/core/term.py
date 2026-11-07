"""Fall 2026 term (seed/fall2026_term.json, from the Duke Registrar): dining days skip breaks."""
import json
from datetime import date, timedelta
from functools import cache
from pathlib import Path

TERM = Path(__file__).resolve().parents[2] / "seed" / "fall2026_term.json"


@cache
def data() -> dict:
    return json.loads(TERM.read_text())


def start() -> date:
    return date.fromisoformat(data()["start"])


def end() -> date:
    return date.fromisoformat(data()["end"])


@cache
def break_days() -> frozenset[date]:
    out = set()
    for b in data()["breaks"]:
        d, last = date.fromisoformat(b["from"]), date.fromisoformat(b["to"])
        while d <= last:
            out.add(d)
            d += timedelta(days=1)
    return frozenset(out)


def dining_days(a: date, b: date, breaks: frozenset[date] | None = None) -> int:
    """Days d with a <= d < b that aren't break days."""
    breaks = break_days() if breaks is None else breaks
    return sum(1 for i in range((b - a).days) if a + timedelta(days=i) not in breaks)


def add_dining_days(day: date, n: int, breaks: frozenset[date] | None = None) -> date:
    """The date n dining days after `day` (break days don't count)."""
    breaks = break_days() if breaks is None else breaks
    while n > 0:
        day += timedelta(days=1)
        if day not in breaks:
            n -= 1
    return day
