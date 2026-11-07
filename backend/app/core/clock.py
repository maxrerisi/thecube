"""'Today' and 'now' in America/New_York, overridable by DEMO_TODAY (SPEC 8)."""
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def now() -> datetime:
    """Aware NY datetime. With DEMO_TODAY set, the date is replaced and the clock time kept,
    so 'after 5 PM' logic still follows the real time of day during a demo."""
    real = datetime.now(NY)
    demo = os.environ.get("DEMO_TODAY")
    if demo:
        d = date.fromisoformat(demo)
        return real.replace(year=d.year, month=d.month, day=d.day)
    return real


def today() -> date:
    return now().date()


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """[start, end) of a local day, as UTC datetimes for querying timestamptz columns."""
    start = datetime.combine(d, time.min, NY)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
