from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import require_token
from app.db import get_conn
from app.ingest.importer import import_emls
from app.ingest.receipt_parser import NotAReceipt

router = APIRouter(dependencies=[Depends(require_token)])


@router.post("/import/eml")
async def import_eml(user_id: int = Form(...), files: list[UploadFile] = File(...), conn=Depends(get_conn)):
    if not conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone():
        raise HTTPException(404, f"no user {user_id}")
    blobs = [await f.read() for f in files]
    try:
        return import_emls(conn, user_id, blobs)
    except (NotAReceipt, ValueError) as e:  # not a receipt, or a receipt that doesn't parse
        raise HTTPException(422, str(e))
