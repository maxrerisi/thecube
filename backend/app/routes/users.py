from fastapi import APIRouter, Depends

from app.auth import require_token
from app.db import get_conn
from app.schemas import User

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/users", response_model=list[User])
def list_users(conn=Depends(get_conn)):
    return conn.execute("SELECT id, name, is_demo FROM users ORDER BY id").fetchall()
