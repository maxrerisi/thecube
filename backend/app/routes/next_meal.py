from typing import Literal

from fastapi import APIRouter, Depends

from app.auth import require_token
from app.coach import gemini
from app.core import optimizer
from app.db import get_conn

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/next-meal")
def next_meal(user_id: int, bias: Literal["balanced", "protein", "cheap"] | None = None, conn=Depends(get_conn)):
    """bias omitted = from the user's goal (build_muscle -> protein, budget -> cheap)."""
    result = optimizer.suggest(conn, user_id, bias)
    result["coach"] = gemini.pick(result, result["show_calories"], conn)
    return result
