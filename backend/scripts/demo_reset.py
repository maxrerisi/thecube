"""Reset the demo on any server (local or Railway): POST /admin/reset-demo, then upload
William's receipts from emails/ (a deployed server has no emails/).

  ../.venv/bin/python scripts/demo_reset.py --base https://...railway.app [--hold-back 1]

--hold-back N keeps the N newest receipts out, so one can be forwarded live (rehearse.py does).
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


def receipts(hold_back: int) -> tuple[list[Path], list[Path]]:
    files = sorted(EMAILS.glob("*.eml"), key=lambda p: int(p.name.split()[0].lstrip("#")))  # order no. ~ time
    return (files[:-hold_back], files[-hold_back:]) if hold_back else (files, [])


def reset(base: str, token: str, hold_back: int = 0) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{base}/admin/reset-demo", headers=h, params={"emails": "false"}, timeout=120)
    r.raise_for_status()
    out = {"reset": r.json()}
    users = requests.get(f"{base}/users", headers=h, timeout=30).json()
    william = next(u["id"] for u in users if u["name"] == "William")
    upload, held = receipts(hold_back)
    if upload:
        files = [("files", (p.name, p.read_bytes(), "message/rfc822")) for p in upload]
        r = requests.post(f"{base}/import/eml", headers=h, data={"user_id": william}, files=files, timeout=120)
        r.raise_for_status()
        out["import"] = {k: (len(v) if isinstance(v, list) else v) for k, v in r.json().items()}
    out["held_back"] = [p.name for p in held]
    return out


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--hold-back", type=int, default=0)
    a = ap.parse_args()
    if not os.environ.get("APP_TOKEN"):
        sys.exit("APP_TOKEN not set (backend/.env)")
    print(reset(a.base.rstrip("/"), os.environ["APP_TOKEN"], a.hold_back))


if __name__ == "__main__":
    main()
