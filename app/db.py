import os
from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (register tables)

DEFAULT_URL = "sqlite:///dukedining.db"


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DUKEDINING_DB", DEFAULT_URL)
    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    return engine


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def set_engine(engine: Engine) -> None:
    global _engine
    _engine = engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s
