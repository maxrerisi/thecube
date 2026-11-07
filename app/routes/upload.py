from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlmodel import Session, func, select

from dukedining.money import money

from ..deps import session_dep, user_dep
from ..models import Receipt, Transaction, User
from ..services import ingest
from ..web import render

router = APIRouter()


def _record_counts(session: Session, user: User) -> dict:
    def n(model):
        return session.exec(select(func.count()).select_from(model).where(model.user_id == user.id)).one()

    n_r, n_t = n(Receipt), n(Transaction)
    return {"n_receipts": n_r, "n_transactions": n_t}


@router.get("/upload")
def upload_page(request: Request, session: Session = Depends(session_dep), user: User = Depends(user_dep)):
    return render(request, "upload.html", session, user, active="upload", **_record_counts(session, user))


@router.post("/upload")
async def upload(
    request: Request,
    receipt_files: list[UploadFile] = File(default=[]),
    receipt_text: str = Form(""),
    eaccounts_text: str = Form(""),
    eaccounts_file: UploadFile | None = File(default=None),
    balance: str = Form(""),
    session: Session = Depends(session_dep),
    user: User = Depends(user_dep),
):
    files = [(f.filename or "upload", await f.read()) for f in receipt_files if f.filename]
    receipts, r_errors = ingest.parse_receipt_inputs(files, receipt_text)

    ea_text = eaccounts_text
    if eaccounts_file is not None and eaccounts_file.filename:
        ea_text = (ea_text + "\n" if ea_text.strip() else "") + (await eaccounts_file.read()).decode(
            "utf-8", errors="replace"
        )
    rows, e_errors = ingest.parse_eaccounts_input(ea_text)

    reported: Decimal | None = None
    if balance.strip():
        try:
            reported = money(balance)
        except InvalidOperation:
            e_errors.append(f"current balance {balance!r} isn't a number")

    r_sum = ingest.import_receipts(session, user, receipts, r_errors) if (receipts or r_errors) else None
    e_sum = None
    if rows or e_errors or reported is not None:
        e_sum = ingest.import_eaccounts(session, user, rows, reported, e_errors)
    nothing = r_sum is None and e_sum is None
    ctx = {
        "r": r_sum,
        "e": e_sum,
        "nothing": nothing,
        "need_review": (e_sum or r_sum).need_review if not nothing else 0,
        **_record_counts(session, user),
    }
    if request.headers.get("HX-Request"):
        return render(request, "_summary.html", session, user, **ctx)
    return render(request, "upload.html", session, user, active="upload", summary=True, **ctx)
