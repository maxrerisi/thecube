from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app import settings_store
from app.auth import require_token
from app.db import get_conn
from app.schemas import Settings

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/settings", response_model=Settings)
def get_settings(user_id: int, conn=Depends(get_conn)):
    return settings_store.load(conn, user_id)[1]


@router.put("/settings", response_model=Settings)
def put_settings(user_id: int, settings: Settings, conn=Depends(get_conn)):
    settings_store.load(conn, user_id)  # 404 if no such user
    settings_store.save(conn, user_id, settings)
    return settings


class Balance(BaseModel):
    user_id: int
    points: float = Field(ge=0)
    swipes: int | None = Field(default=None, ge=0)


@router.post("/balance")
def post_balance(b: Balance, conn=Depends(get_conn)):
    settings_store.load(conn, b.user_id)
    ts = datetime.now(timezone.utc)
    conn.execute("INSERT INTO balance_snapshots (user_id, ts, points, swipes) VALUES (%s, %s, %s, %s)",
                 (b.user_id, ts, b.points, b.swipes))
    return {"user_id": b.user_id, "ts": ts.isoformat(), "points": b.points, "swipes": b.swipes}
