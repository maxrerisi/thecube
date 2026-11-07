from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..deps import session_dep, user_dep
from ..models import User
from ..services import review
from ..web import render

router = APIRouter()


def _card_ctx(session: Session, user: User, group_id: int | None = None, skipped: bool = False) -> dict:
    c = review.counts(session, user.id)
    card = None
    if group_id is not None:
        try:
            card = review.card_for(session, user.id, group_id)
        except review.ReviewError:
            card = None
    if card is None:
        q = review.queue(session, user.id, include_skipped=skipped)
        card = q[0] if q else None
    position = c["confirmed"] + 1
    total = c["confirmed"] + c["left"] + c["skipped"]
    return {
        "card": card,
        "counts": c,
        "position": position,
        "total": total,
        "suggested": review.suggested_price(card.group) if card else None,
        "skipped_mode": skipped,
    }


@router.get("/review")
def review_page(
    request: Request,
    group_id: int | None = None,
    skipped: bool = False,
    session: Session = Depends(session_dep),
    user: User = Depends(user_dep),
):
    ctx = _card_ctx(session, user, group_id, skipped)
    return render(request, "review.html", session, user, active="review", **ctx)


@router.post("/review/{group_id}")
def review_answer(
    request: Request,
    group_id: int,
    choice: str = Form(""),
    action: str = Form(""),
    other_name: str = Form(""),
    other_price: str = Form(""),
    skipped_mode: bool = Form(False),
    session: Session = Depends(session_dep),
    user: User = Depends(user_dep),
):
    error = None
    result = None
    try:
        if action == "undo":
            review.unconfirm(session, user, group_id)
        else:
            result = review.answer(session, user, group_id, "skip" if action == "skip" else choice,
                                   other_name, other_price)  # fmt: skip
    except review.ReviewError as e:
        error = str(e)
    if not request.headers.get("HX-Request"):
        return RedirectResponse("/review", status_code=303)
    keep = group_id if (error or action == "undo") else None
    ctx = _card_ctx(session, user, keep, skipped_mode)
    return render(
        request, "_review_card.html", session, user, oob=True, error=error, result=result,
        status_code=422 if error else 200, **ctx,
    )  # fmt: skip
