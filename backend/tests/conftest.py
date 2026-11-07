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
        seed_users(conn)


@pytest.fixture(scope="module")
def client():
    reset_db()
    return TestClient(app)
