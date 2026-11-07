import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.routes import admin, imports, manual, menu, next_meal, postmark, settings, today, users, wrapped

NN_JSON = Path(__file__).resolve().parents[2] / "spikes" / "nn.json"
log = logging.getLogger("thecube")


@asynccontextmanager
async def lifespan(_app):
    """Fresh database (e.g. first Railway deploy): schema, menus from spikes/nn.json, users, vendors."""
    from app.db import connect, init_schema
    from app.ingest import netnutrition
    from app.seed import seed_users, seed_vendors
    try:
        with connect() as conn:
            init_schema(conn)
            if NN_JSON.exists() and not conn.execute("SELECT 1 FROM nn_items LIMIT 1").fetchone():
                log.info("startup: loading menus from %s: %s", NN_JSON, netnutrition.write_db(conn, json.loads(NN_JSON.read_text())))
            seed_users(conn)
            if not conn.execute("SELECT 1 FROM vendors LIMIT 1").fetchone():
                for w in seed_vendors(conn):
                    log.warning("startup: %s", w)
    except Exception:  # never block the server from starting (tests use their own DB setup)
        log.exception("startup seeding failed")
    yield


app = FastAPI(title="thecube", lifespan=lifespan)
app.include_router(users.router)
app.include_router(imports.router)
app.include_router(today.router)
app.include_router(settings.router)
app.include_router(menu.router)
app.include_router(manual.router)
app.include_router(next_meal.router)
app.include_router(admin.router)
app.include_router(postmark.router)
app.include_router(wrapped.router)
