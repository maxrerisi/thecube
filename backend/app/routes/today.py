from datetime import timedelta

from fastapi import APIRouter, Depends

from app import settings_store
from app.auth import require_token
from app.coach import gemini
from app.core import budget, clock, macros
from app.db import get_conn

router = APIRouter(dependencies=[Depends(require_token)])


def meals_between(conn, user_id, start, end):
    return conn.execute(
        """SELECT o.id, o.ts, coalesce(v.name, o.vendor_raw) AS vendor, o.vendor_id, o.points_spent, o.swipes_used,
                  o.total, o.source, o.macros_partial,
                  coalesce(array_agg(oi.name ORDER BY oi.id) FILTER (WHERE oi.id IS NOT NULL), '{}') AS items
           FROM orders o LEFT JOIN vendors v ON v.id = o.vendor_id LEFT JOIN order_items oi ON oi.order_id = o.id
           WHERE o.user_id = %s AND o.ts >= %s AND o.ts < %s
           GROUP BY o.id, v.name ORDER BY o.ts""", (user_id, start, end)).fetchall()


def protein_hit_days(conn, user_id, today, target) -> int:
    """How many of the previous 7 full days reached the protein target."""
    hits = 0
    for i in range(1, 8):
        start, end = clock.day_bounds(today - timedelta(days=i))
        ids = [m["id"] for m in meals_between(conn, user_id, start, end)]
        if macros.total(macros.order_macros(conn, ids))["protein_g"] >= target:
            hits += 1
    return hits


def today_payload(conn, user_id: int) -> dict:
    user, s = settings_store.load(conn, user_id)
    today = clock.today()
    start, end = clock.day_bounds(today)
    meals = meals_between(conn, user_id, start, end)
    per = macros.order_macros(conn, [m["id"] for m in meals])
    eaten = macros.total(per)
    if not s.show_calories:
        eaten["calories"] = None
    pts = budget.status(conn, user_id, s.semester_end, today, s.meal_plan)
    return {
        "date": today.isoformat(),
        "user": {"id": user["id"], "name": user["name"], "is_demo": user["is_demo"]},
        "targets": {"calories": s.targets.calories if s.show_calories else None, "protein_g": s.targets.protein_g},
        "show_calories": s.show_calories,
        "semester_end": s.semester_end.isoformat(),
        "eaten": eaten,
        "protein_hit_days_7": protein_hit_days(conn, user_id, today, s.targets.protein_g),
        "points": pts.to_json(),
        "coach": None,  # filled by get_today (kept out of the payload the coach reads)
        "meals": [{
            "id": m["id"], "ts": m["ts"].isoformat(), "vendor": m["vendor"], "items": m["items"],
            "points_spent": float(m["points_spent"]), "swipes_used": m["swipes_used"], "source": m["source"],
            "macros_partial": m["macros_partial"],
            **{k: (None if k == "calories" and not s.show_calories else v) for k, v in per[m["id"]].items()},
        } for m in meals],
    }


@router.get("/today")
def get_today(user_id: int, conn=Depends(get_conn)):
    payload = today_payload(conn, user_id)
    payload["coach"] = gemini.recap(payload, conn)
    return payload
