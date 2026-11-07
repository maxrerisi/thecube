"""Points + swipes budget (SPEC 8). compute() is pure; status() loads from the DB."""
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from app.core import pace
from app.core.clock import NY, day_bounds


@dataclass
class PointsStatus:
    points: float | None          # None = no balance entered yet
    swipes: int | None
    days_left: int
    daily_budget: float | None
    spent_today: float
    trailing_daily: float         # avg points/day over the previous 7 full days
    runout: date | None           # None = lasts to semester end (or no data)
    on_pace: bool | None
    balance_as_of: datetime | None
    meal_plan: str | None = None      # Duke plan letter, for the pace chart
    pace_target: float | None = None  # Duke's suggested balance today for that plan
    vs_pace: float | None = None      # points - pace_target (negative = behind Duke's pace)

    def to_json(self) -> dict:
        d = asdict(self)
        for k in ("runout", "balance_as_of"):
            d[k] = d[k].isoformat() if d[k] else None
        for k in ("points", "daily_budget", "spent_today", "trailing_daily", "pace_target", "vs_pace"):
            d[k] = round(d[k], 2) if d[k] is not None else None
        return d


def compute(snap: dict | None, orders: list[dict], semester_end: date, today: date) -> PointsStatus:
    """snap: {ts, points, swipes} or None. orders: [{ts (aware), points_spent, swipes_used}]."""
    def local_day(o):
        return o["ts"].astimezone(NY).date()

    days_left = max((semester_end - today).days, 1)
    spent_today = sum(float(o["points_spent"]) for o in orders if local_day(o) == today)
    window = {today - timedelta(days=i) for i in range(1, 8)}
    trailing = sum(float(o["points_spent"]) for o in orders if local_day(o) in window) / 7
    if snap is None:
        return PointsStatus(None, None, days_left, None, spent_today, trailing, None, None, None)
    after = [o for o in orders if o["ts"] > snap["ts"]]
    points = float(snap["points"]) - sum(float(o["points_spent"]) for o in after)
    swipes = (snap["swipes"] - sum(o["swipes_used"] for o in after)) if snap["swipes"] is not None else None
    daily_budget = points / days_left
    runout = today + timedelta(days=math.floor(points / trailing)) if trailing > 0 else None
    if runout is not None and runout >= semester_end:
        runout = None
    return PointsStatus(points, swipes, days_left, daily_budget, spent_today, trailing, runout,
                        trailing <= daily_budget, snap["ts"])


def status(conn, user_id: int, semester_end: date, today: date, meal_plan: str | None = None) -> PointsStatus:
    _, end_of_today = day_bounds(today)
    snap = conn.execute("""SELECT ts, points, swipes FROM balance_snapshots WHERE user_id = %s AND ts < %s
                           ORDER BY ts DESC LIMIT 1""", (user_id, end_of_today)).fetchone()
    start, _ = day_bounds(today - timedelta(days=7))
    since = min(snap["ts"], start) if snap else start
    orders = conn.execute("""SELECT ts, points_spent, swipes_used FROM orders
                             WHERE user_id = %s AND ts >= %s AND ts < %s""",
                          (user_id, since, end_of_today)).fetchall()
    s = compute(snap, orders, semester_end, today)
    s.meal_plan, s.pace_target = meal_plan, pace.target(meal_plan, today)
    if s.points is not None and s.pace_target is not None:
        s.vs_pace = s.points - s.pace_target
    return s
