import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from ..deps import session_dep, user_dep
from ..models import SharedCatalogEntry, User, UserCatalogEntry
from ..services import purchases, stats
from ..services.privacy import delete_all_user_data
from ..web import render

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    deleted: bool = False,
    session: Session = Depends(session_dep),
    user: User = Depends(user_dep),
):
    d = stats.build(session, user.id)
    charts = {
        "weeks": [f"{w:%b} {w.day}" for w, _ in d.by_week],
        "week_values": [c / 100 for _, c in d.by_week],
        "locations": [name for name, _ in d.by_location],
        "location_values": [c / 100 for _, c in d.by_location],
    }
    return render(request, "dashboard.html", session, user, active="dashboard", d=d,
                  charts_json=json.dumps(charts), deleted=deleted)  # fmt: skip


@router.get("/purchases")
def purchases_page(
    request: Request,
    show: str = "food",
    session: Session = Depends(session_dep),
    user: User = Depends(user_dep),
):
    show = show if show in ("food", "all", "review") else "food"
    rows = purchases.rows(session, user.id, show)
    return render(request, "purchases.html", session, user, active="purchases", rows=rows, show=show)


@router.get("/catalog")
def catalog_page(request: Request, session: Session = Depends(session_dep), user: User = Depends(user_dep)):
    mine = session.exec(
        select(UserCatalogEntry)
        .where(UserCatalogEntry.user_id == user.id)
        .order_by(UserCatalogEntry.location, UserCatalogEntry.kind, UserCatalogEntry.item)
    ).all()
    shared = session.exec(
        select(SharedCatalogEntry).order_by(SharedCatalogEntry.location, SharedCatalogEntry.item)
    ).all()
    by_loc: dict[str, list] = {}
    for e in mine:
        by_loc.setdefault(e.location, []).append(e)
    return render(request, "catalog.html", session, user, active="catalog", by_loc=by_loc, shared=shared)


@router.get("/privacy")
def privacy_page(request: Request, session: Session = Depends(session_dep), user: User = Depends(user_dep)):
    return render(request, "privacy.html", session, user, active="privacy")


@router.post("/privacy/delete")
def delete_everything(
    confirm: str = Form(""), session: Session = Depends(session_dep), user: User = Depends(user_dep)
):
    if confirm.strip().upper() != "DELETE":
        return RedirectResponse("/privacy?error=1", status_code=303)
    delete_all_user_data(session, user.id)
    return RedirectResponse("/?deleted=1", status_code=303)
