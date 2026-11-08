"""Reset the demo: POST /admin/reset-demo. The server rebuilds Blue Devil (the only account),
reading the real receipts in emails/ as a price list only.

  ../.venv/bin/python scripts/demo_reset.py [--base http://localhost:8000]

Reads APP_TOKEN (and --base default API_BASE_URL) from the environment / backend/.env.
"""
import argparse
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
EMAILS = HERE.parents[1] / "emails"


def load_env():
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip())


def receipts() -> list[Path]:
    return sorted(EMAILS.glob("*.eml"), key=lambda p: int(p.name.split()[0].lstrip("#")))  # order no. ~ time


def reset(base: str, token: str) -> dict:
    r = requests.post(f"{base}/admin/reset-demo", headers={"Authorization": f"Bearer {token}"}, timeout=180)
    r.raise_for_status()
    return {"reset": r.json()}


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    a = ap.parse_args()
    if not os.environ.get("APP_TOKEN"):
        sys.exit("APP_TOKEN not set (backend/.env)")
    print(reset(a.base.rstrip("/"), os.environ["APP_TOKEN"]))


if __name__ == "__main__":
    main()
