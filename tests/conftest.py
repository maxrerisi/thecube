from pathlib import Path

import pytest

from dukedining.eaccounts import load_csv
from dukedining.receipts import parse_receipts

FIXTURES = Path(__file__).parent / "fixtures"
REAL_DATA = Path(__file__).parent.parent / "data"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def receipts():
    return parse_receipts((FIXTURES / "receipts.txt").read_text())


@pytest.fixture
def ea_rows():
    return load_csv((FIXTURES / "eaccounts.csv").read_text())


@pytest.fixture
def session():
    from sqlmodel import Session

    from app.db import make_engine

    engine = make_engine("sqlite://")
    with Session(engine) as s:
        yield s


@pytest.fixture
def user(session):
    from app.services.users import current_user

    return current_user(session)


@pytest.fixture
def loaded(session, user, receipts, ea_rows):
    """Fixture receipts + eAccounts CSV imported into a fresh DB."""
    from app.services import ingest

    ingest.import_receipts(session, user, receipts)
    ingest.import_eaccounts(session, user, ea_rows)
    return session, user


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from sqlmodel import Session

    from app import db
    from app.main import create_app

    engine = db.make_engine("sqlite://")
    db.set_engine(engine)
    with TestClient(create_app()) as c:
        c.engine = engine
        c.db = lambda: Session(engine)
        yield c
    db.set_engine(None)


@pytest.fixture
def loaded_client(client, fixtures):
    r = client.post(
        "/upload",
        files=[("receipt_files", ("r.txt", (fixtures / "receipts.txt").read_bytes(), "text/plain"))],
        data={"eaccounts_text": (fixtures / "eaccounts.csv").read_text()},
    )
    assert r.status_code == 200
    return client
