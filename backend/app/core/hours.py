"""Vendor hours: {"mon": [["11:00", "21:00"], ...]} in local (America/New_York) time."""
from datetime import datetime, timedelta

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday() order


def _windows(hours: dict, at: datetime):
    """Yield (open, close) datetimes for the day of `at` and the day before (for past-midnight closes)."""
    for back in (1, 0):
        d = (at - timedelta(days=back)).date()
        for o, c in hours.get(DAY_KEYS[d.weekday()], []):
            start = datetime.combine(d, datetime.strptime(o, "%H:%M").time(), at.tzinfo)
            end = datetime.combine(d, datetime.strptime(c, "%H:%M").time(), at.tzinfo)
            if end <= start:
                end += timedelta(days=1)
            yield start, end


def is_open(hours: dict, at: datetime) -> bool:
    return any(s <= at < e for s, e in _windows(hours, at))


def opens_within(hours: dict, at: datetime, within: timedelta) -> datetime | None:
    """Next opening time within `within` from `at` (None if open now or not soon)."""
    if is_open(hours, at):
        return None
    starts = [s for s, _ in _windows(hours, at) if at < s <= at + within]
    nxt = at + timedelta(days=1)
    starts += [s for s, _ in _windows(hours, nxt) if at < s <= at + within]
    return min(starts) if starts else None
