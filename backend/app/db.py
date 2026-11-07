"""Postgres access: psycopg 3, plain SQL."""
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://localhost/thecube")


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text())


def get_conn() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one connection per request, committed on success."""
    with connect() as conn:  # commits on clean exit, rolls back on exception
        yield conn
