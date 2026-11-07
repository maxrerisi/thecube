# Runbook: from this repo to the live demo

Everything below "You" needs an account or a GUI only a person can use. Everything else
is already built and tested (`spec-build` branch).

## Status by ticket

| Ticket | State | Check |
| --- | --- | --- |
| T1 schema, auth, /users | Done locally; **not deployed** | `pytest tests/test_auth_users.py` |
| T2 scraper → DB | Done | `python -m app.ingest.netnutrition --units 8,21,19,18,16,5,20,11,10 --write-db` |
| T3 receipt import | Done (incl. forwarded receipts) | `pytest tests/test_import.py -s` |
| T5 budget + /today | Done | `pytest tests/test_budget.py` |
| T6 vendors, menu, manual log | Done | `pytest tests/test_manual.py` |
| T8 Jordan + reset-demo | Done | `pytest tests/test_demo.py` |
| T9 optimizer + /next-meal | Done | `pytest tests/test_optimizer.py` |
| T11 coach | Backend done, live Gemini verified | `pytest tests/test_coach.py` |
| T12 Postmark | Code done; **needs deploy + Postmark account** | `pytest tests/test_postmark.py` |
| T4/T7/T10/T13 iOS | Written; **never built (no Xcode on the dev Mac)** | build in Xcode |
| T14 rehearsal | 2/2 clean against a local server | `scripts/rehearse.py --runs 2` |

All backend tests: `cd backend && ../.venv/bin/pytest -q` (58 pass).

## Local (5 minutes)

```bash
brew services start postgresql@18 && createdb thecube        # once
cd backend && ../.venv/bin/python -m app.seed --demo          # schema, menus, William, Jordan
set -a; source .env; set +a; ../.venv/bin/uvicorn app.main:app --port 8000
```
`backend/.env` (gitignored) holds APP_TOKEN, GEMINI_API_KEY, POSTMARK_WEBHOOK_USER/PASS.
Optional `WILLIAM_BALANCE=points,swipes,2026-11-07T09:00-05:00` (William's real balance; every
reset restores it). For a stable demo day set `DEMO_TODAY=YYYY-MM-DD`.

## You: iOS (Xcode)

1. Install Xcode from the App Store, then `sudo xcode-select -s /Applications/Xcode.app`.
2. `cp ios/Config/Secrets.example.xcconfig ios/Config/Secrets.xcconfig`; set APP_TOKEN (from
   `backend/.env`) and API_BASE_URL (`http:/$()/localhost:8000` for the simulator; the Railway
   URL for a phone). Leave API_BASE_URL empty to run on bundled mock data (Jordan).
3. Open `ios/thecube.xcodeproj`, pick your team under Signing, run. Fix any compile errors:
   models/API/view models compile; the SwiftUI views have never been compiled.

## You: deploy (Railway)

1. New project from GitHub repo `maxrerisi/thecube`, branch `spec-build`, root = repo root
   (the `Dockerfile` is detected). Add a Postgres plugin.
2. Variables: DATABASE_URL (from the plugin), APP_TOKEN, GEMINI_API_KEY, GEMINI_MODEL,
   POSTMARK_WEBHOOK_USER, POSTMARK_WEBHOOK_PASS, DEMO_TODAY (optional), WILLIAM_BALANCE (optional).
3. First boot creates the schema, loads menus from `spikes/nn.json`, seeds users + vendors.
4. From a laptop with `emails/`: `cd backend/scripts && ../../.venv/bin/python demo_reset.py --base https://<app>.up.railway.app`
   (uploads William's receipts; the image never contains `emails/`).

## You: Postmark (live forwarding)

1. Postmark → Servers → your server → Inbound stream → webhook URL:
   `https://POSTMARK_WEBHOOK_USER:POSTMARK_WEBHOOK_PASS@<app>.up.railway.app/ingest/postmark`
2. William forwards a receipt from Outlook to the server's inbound address. The sender must be
   the Duke address the receipts were sent to (that's `users.email`).
3. Test once before the pitch; the parser handles inline forwards and attachments (tested on
   simulated forwards of all 31 receipts, never on a real Outlook forward).

## Before the pitch

```bash
cd backend/scripts && ../../.venv/bin/python rehearse.py --base https://<app>.up.railway.app --runs 2
../../.venv/bin/python demo_reset.py --base https://<app>.up.railway.app --hold-back 0
```
`rehearse.py` resets with the newest receipt held back and forwards it through Postmark's
endpoint, so its own run doesn't need a real email.
