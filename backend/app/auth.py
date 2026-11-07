"""Bearer-token auth (SPEC 12): every route except /ingest/postmark needs APP_TOKEN."""
import hmac
import os

from fastapi import Header, HTTPException


def require_token(authorization: str | None = Header(default=None)) -> None:
    token = os.environ.get("APP_TOKEN")
    if not token:
        raise HTTPException(500, "APP_TOKEN is not set on the server")
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "missing or invalid bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
