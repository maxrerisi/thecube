"""Wrapped: a semester-so-far recap story (8 slides). Code computes every number and label here;
the coach only writes one caption per slide (app/coach/gemini.py, kind "wrapped").

compute(conn, user_id, today) -> {"term", "as_of", "slides": [{id, title, big, unit, facts}]}
or None when there are no orders yet.
"""
from collections import Counter
from zoneinfo import ZoneInfo

from app import settings_store
from app.core import budget, clock, macros, term

LOCAL = ZoneInfo("America/New_York")
EGG_PROTEIN_G = 6  # one large egg


def _hour_label(h: int) -> str:
    return f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"


def _time_label(t) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _date_words(d) -> str | None:
    if not d:
        return None
    from datetime import date
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d:%B} {d.day}"


def personality(vs_pace: float | None, trailing: float | None, daily: float | None) -> tuple[str, str]:
    """Points personality, picked by thresholds (code, not the model)."""
    gap = vs_pace
    if gap is None and trailing is not None and daily:
        gap = (daily - trailing) * 10  # rough: ten days at the current gap
    if gap is None:
        return "The Newcomer", "Still finding your rhythm."
    if gap < -50:
        return "The Sprinter", "Spends fast and early in the semester."
    if gap > 50:
        return "The Squirrel", "Stashing points for later."
    return "The Metronome", "Right on an even pace."


def compute(conn, user_id: int, today=None) -> dict | None:
    today = today or clock.today()
    _, s = settings_store.load(conn, user_id)
    start, _ = clock.day_bounds(term.start())
    _, end = clock.day_bounds(today)
    orders = conn.execute(
        """SELECT o.id, o.ts, coalesce(v.name, o.vendor_raw) AS vendor, o.points_spent
           FROM orders o LEFT JOIN vendors v ON v.id = o.vendor_id
           WHERE o.user_id = %s AND o.ts >= %s AND o.ts < %s ORDER BY o.ts""", (user_id, start, end)).fetchall()
    if not orders:
        return None

    meals = len(orders)
    points_spent = round(sum(float(o["points_spent"]) for o in orders), 2)
    protein = round(macros.total(macros.order_macros(conn, [o["id"] for o in orders]))["protein_g"])
    days = term.dining_days(term.start(), today)

    by_vendor = Counter(o["vendor"] for o in orders)
    top_vendor, visits = by_vendor.most_common(1)[0]

    sig = conn.execute(
        """SELECT oi.name, coalesce(v.name, o.vendor_raw) AS vendor, count(*) AS n
           FROM order_items oi JOIN orders o ON o.id = oi.order_id LEFT JOIN vendors v ON v.id = o.vendor_id
           WHERE o.user_id = %s AND o.ts >= %s AND o.ts < %s
           GROUP BY 1, 2 ORDER BY n DESC, 1 LIMIT 1""", (user_id, start, end)).fetchone()

    local = [o["ts"].astimezone(LOCAL) for o in orders]
    hours = Counter(t.hour for t in local)
    peak, at_peak = max(hours.items(), key=lambda kv: (kv[1], -kv[0]))
    latest = max(local, key=lambda t: ((t.hour - 5) % 24, t.minute))  # nights run past midnight

    pts = budget.status(conn, user_id, s.semester_end, today, s.meal_plan)
    name, blurb = personality(pts.vs_pace, pts.trailing_daily, pts.daily_budget)
    pace = {}
    if pts.vs_pace is not None:
        gap = round(abs(pts.vs_pace))
        pace = {"behind_pace_by": gap} if pts.vs_pace < 0 else {"ahead_of_pace_by": gap}

    slides = [
        {"id": "intro", "title": "Your Fall 2026 so far", "big": str(days), "unit": "dining days in",
         "facts": {"term": term.data()["term"], "dining_days_so_far": days}},
        {"id": "totals", "title": "You ate", "big": str(meals), "unit": "meals",
         "facts": {"meals": meals, "points_spent": points_spent, "places_tried": len(by_vendor)}},
        {"id": "top_spot", "title": "Your spot", "big": top_vendor, "unit": f"{visits} visits",
         "facts": {"vendor": top_vendor, "visits": visits, "share_of_meals_pct": round(100 * visits / meals)}},
        {"id": "signature", "title": "Your signature order", "big": sig["name"], "unit": f"{sig['n']} times",
         "facts": {"item": sig["name"], "vendor": sig["vendor"], "times": sig["n"]}},
        {"id": "protein", "title": "Protein, all semester", "big": f"{protein:,}", "unit": "grams",
         "facts": {"protein_total_g": protein, "eggs_equivalent": round(protein / EGG_PROTEIN_G)}},
        {"id": "peak_hour", "title": "Your hungriest hour", "big": _hour_label(peak), "unit": f"{at_peak} meals",
         "facts": {"peak_hour": _hour_label(peak), "meals_at_peak": at_peak, "latest_order": _time_label(latest)}},
        {"id": "personality", "title": "Your points personality", "big": name, "unit": blurb,
         "facts": {"personality": name, "points_left": None if pts.points is None else round(pts.points, 2), "runs_out_on": _date_words(pts.runout), **pace}},
        {"id": "share", "title": "Fall 2026, wrapped", "big": f"{meals} meals", "unit": f"{protein:,} g protein",
         "facts": {"term": term.data()["term"], "meals": meals, "top_vendor": top_vendor, "protein_total_g": protein, "personality": name}},
    ]
    return {"term": term.data()["term"], "as_of": today.isoformat(), "slides": slides}
