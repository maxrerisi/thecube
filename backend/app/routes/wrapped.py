from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_token
from app.coach import gemini
from app.core import wrapped
from app.db import get_conn

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/wrapped")
def get_wrapped(user_id: int, conn=Depends(get_conn)):
    """Semester-so-far story: numbers from code, one caption per slide from the coach."""
    story = wrapped.compute(conn, user_id)
    if story is None:
        raise HTTPException(404, "no meals yet this term")
    words = gemini.wrapped(story, conn)
    for s, cap in zip(story["slides"], words["captions"]):
        s["caption"] = cap
        del s["facts"]
    story["caption_source"] = words["source"]
    return story
