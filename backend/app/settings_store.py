"""Load/save a user's Settings (SPEC 9) from users.settings JSONB."""
import json

from fastapi import HTTPException

from app.schemas import Settings


def load(conn, user_id: int) -> tuple[dict, Settings]:
    row = conn.execute("SELECT id, name, is_demo, settings FROM users WHERE id = %s", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"no user {user_id}")
    return row, Settings.model_validate(row["settings"])


def save(conn, user_id: int, settings: Settings) -> None:
    conn.execute("UPDATE users SET settings = %s WHERE id = %s",
                 (json.dumps(settings.model_dump(mode="json")), user_id))
