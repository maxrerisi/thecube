from sqlmodel import Session, delete, select

from ..models import (
    ImportBatch,
    Match,
    PurchaseGroup,
    Receipt,
    ReceiptItem,
    Transaction,
    User,
    UserCatalogEntry,
)


def delete_all_user_data(session: Session, user_id: int) -> None:
    """Hard-delete everything belonging to this user, including the user row.

    The shared catalog is untouched: it holds no user ids, so contributions can't be traced
    back (or removed) by design. The upload page says so next to the opt-in checkbox."""
    receipt_ids = select(Receipt.id).where(Receipt.user_id == user_id)
    session.exec(delete(Match).where(Match.user_id == user_id))
    session.exec(delete(Transaction).where(Transaction.user_id == user_id))
    session.exec(delete(PurchaseGroup).where(PurchaseGroup.user_id == user_id))
    session.exec(delete(ReceiptItem).where(ReceiptItem.receipt_id.in_(receipt_ids)))
    session.exec(delete(Receipt).where(Receipt.user_id == user_id))
    session.exec(delete(UserCatalogEntry).where(UserCatalogEntry.user_id == user_id))
    session.exec(delete(ImportBatch).where(ImportBatch.user_id == user_id))
    session.exec(delete(User).where(User.id == user_id))
    session.commit()
    session.exec(select(User).limit(0))  # keep the session usable
