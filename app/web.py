"""Template setup and shared page context."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from .models import User
from .money_db import fmt
from .services import recompute

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _when(dt: datetime | None, style: str = "full") -> str:
    if dt is None:
        return ""
    if style == "date":
        return f"{dt:%a %b} {dt.day}"
    if style == "time":
        return dt.strftime("%I:%M %p").lstrip("0")
    return f"{dt:%a %b} {dt.day} · {dt.strftime('%I:%M %p').lstrip('0')}"


TEMPLATES.env.filters["money"] = fmt
TEMPLATES.env.filters["when"] = _when


def render(request: Request, name: str, session: Session, user: User, status_code: int = 200, **ctx):
    ctx.setdefault("nav_review", recompute.stats(session, user.id).need_review)
    ctx.setdefault("user", user)
    return TEMPLATES.TemplateResponse(request, name, ctx, status_code=status_code)
