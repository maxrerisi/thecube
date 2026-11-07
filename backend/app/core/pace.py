"""Duke's Fall 2026 points pace chart (seed/duke_points_fall2026.json): the balance Duke
suggests a plan should have on a given day. Linear between the chart's weekly rows."""
import json
from datetime import date
from functools import cache
from pathlib import Path

CHART = Path(__file__).resolve().parents[2] / "seed" / "duke_points_fall2026.json"


@cache
def chart() -> dict:
    return json.loads(CHART.read_text())


def plans() -> list[str]:
    return list(chart()["plans"])


def target(plan: str | None, day: date) -> float | None:
    """Duke's suggested balance for `plan` on `day` (None if no plan / unknown plan)."""
    c = chart()
    if not plan or plan not in c["plans"]:
        return None
    dates = [date.fromisoformat(d) for d in c["dates"]]
    bal = c["plans"][plan]["balances"]
    if day <= dates[0]:
        return bal[0]
    if day >= dates[-1]:
        return bal[-1]
    for i in range(1, len(dates)):
        if day <= dates[i]:
            d0, d1 = dates[i - 1], dates[i]
            f = (day - d0).days / (d1 - d0).days
            return round(bal[i - 1] + (bal[i] - bal[i - 1]) * f, 2)
    return None
