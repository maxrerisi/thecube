"""Tests run against a throwaway database (thecube_test), rebuilt per test module."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://localhost/thecube_test")
os.environ["APP_TOKEN"] = "test-token"

import pytest
from fastapi.testclient import TestClient

from app.db import connect, init_schema
from app.main import app
from app.seed import seed_users

AUTH = {"Authorization": "Bearer test-token"}


def reset_db():
    assert "test" in os.environ["DATABASE_URL"], "refusing to reset a non-test database"
    with connect() as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        init_schema(conn)
        conn.execute("ALTER SEQUENCE users_id_seq RESTART WITH 2")  # Blue Devil is user 2, as on the live DB
        seed_users(conn)


@pytest.fixture(scope="module")
def client():
    reset_db()
    return TestClient(app)


def load_menus_and_vendors():
    """Load spikes/nn.json into nn_* tables and seed vendors/aliases (needs a reset DB)."""
    import json
    from pathlib import Path
    from app.ingest import netnutrition
    from app.seed import seed_vendors
    nn = Path(__file__).resolve().parents[2] / "spikes" / "nn.json"
    with connect() as conn:
        netnutrition.write_db(conn, json.loads(nn.read_text()))
        return seed_vendors(conn)


@pytest.fixture(scope="module")
def menus(client):
    assert load_menus_and_vendors() == []
    return client
