from collections.abc import Iterator

from fastapi import Depends
from sqlmodel import Session

from .db import get_session
from .models import User
from .services.users import current_user


def session_dep() -> Iterator[Session]:
    yield from get_session()


def user_dep(session: Session = Depends(session_dep)) -> User:
    return current_user(session)
