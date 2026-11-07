from sqlmodel import Session, select

from ..models import User


def current_user(session: Session) -> User:
    """Auth stub: a single demo user, created on first use."""
    user = session.exec(select(User).order_by(User.id)).first()
    if user is None:
        user = User()
        session.add(user)
        session.commit()
        session.refresh(user)
    return user
