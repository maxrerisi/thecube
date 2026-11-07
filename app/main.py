"""FastAPI app. Run: uv run uvicorn app.main:app --reload"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import upload


def create_app() -> FastAPI:
    app = FastAPI(title="Duke Dining Tracker", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(upload.router)
    return app


app = create_app()
