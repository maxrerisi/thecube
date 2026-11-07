from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.auth import require_token
from app.db import connect
from app.ingest import netnutrition

router = APIRouter(prefix="/admin", dependencies=[Depends(require_token)])


def _run_scrape(units: list[int] | None) -> None:
    data = netnutrition.scrape(units)
    with connect() as conn:
        netnutrition.log("db:", netnutrition.write_db(conn, data))


@router.post("/scrape")
def scrape(background: BackgroundTasks, units: str | None = None):
    """units: comma-separated unitOids; omitted = all units (~45 min uncached)."""
    try:
        oids = [int(x) for x in units.split(",")] if units else None
    except ValueError:
        raise HTTPException(422, "units must be comma-separated integers")
    background.add_task(_run_scrape, oids)
    return {"started": True, "units": oids or "all"}


@router.post("/reset-demo")
def reset_demo(emails: bool = True):
    """emails=false: skip importing emails/ (scripts/demo_reset.py uploads them itself)."""
    from app import demo
    with connect() as conn:
        return demo.reset(conn, import_emails=emails)
