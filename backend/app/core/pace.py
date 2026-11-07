"""Points pace for a Duke meal plan (our numbers): the plan's starting balance spread evenly
over the Fall 2026 dining days (Registrar calendar, breaks excluded; app/core/term.py).
target(plan, day) = balance you'd have at the start of `day` if you'd spent evenly so far."""
from datetime import date

from app.core import term


def plans() -> list[str]:
    return list(term.data()["plan_start_points"])


def daily(plan: str) -> float | None:
    start = term.data()["plan_start_points"].get(plan)
    if start is None:
        return None
    return start / term.dining_days(term.start(), term.end() + __import__("datetime").timedelta(days=1))


def target(plan: str | None, day: date) -> float | None:
    if not plan or plan not in term.data()["plan_start_points"]:
        return None
    start_pts = term.data()["plan_start_points"][plan]
    if day <= term.start():
        return start_pts
    used = term.dining_days(term.start(), min(day, term.end()))
    return round(max(start_pts - daily(plan) * used, 0.0), 2)
