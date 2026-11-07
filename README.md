# Duke Dining Tracker

See what you actually bought with your DukeCard. eAccounts only shows *where* and *how much*
("Il Forno ILFReg1, $13.81"). This app matches each charge to real menu items, asks you when a
charge could be more than one thing, and shows where your Food Points go and when they'll run out.

## Quick start

```bash
make install
make demo
```

`make demo` seeds a synthetic semester and serves http://localhost:8000. See [DEMO.md](DEMO.md).

| Command | What it does |
|---|---|
| `make test` | pytest (synthetic fixtures; the real-data regression tests skip when `data/` is absent) |
| `make lint` | ruff check + format check |
| `make dev` | run the app with reload |
| `make seed` | reset `dukedining.db` with the synthetic demo data |
| `make report` | the original CLI report: `data/*` → `out/*.csv` |

## How it works

- **Receipts** (`.eml` files, or pasted text) give itemized mobile orders. Each receipt is checked
  end to end: items → subtotal → tax (7.5%, rounded half-up, only above any board-swipe value)
  → total → payments.
- **eAccounts** (the pasted table or a CSV) gives every charge. Rows that belong to one purchase are
  combined: Food / Food - Orientation splits, and $0.10 void pairs.
- **Mobile orders** are matched to receipts when the times are within 2 minutes and the amount
  equals the Student Food payment. These matches also teach which eAccounts terminal code maps to
  which location.
- **In-person charges** are matched against a price catalog: up to 3 lines whose taxed total
  equals the charge exactly. Your own catalog is tried first, then the opt-in community catalog.
  Uncertain charges go to the review queue, and every answer re-runs matching.

Code layout: `dukedining/` is the pure domain logic, with no web or database code. `app/` is
FastAPI + SQLModel (SQLite), Jinja2 + HTMX, and Chart.js. `scripts/seed_demo.py` builds the
synthetic demo.

## Privacy and constraints

- The app never asks for, handles, or stores NetID passwords. It never logs in to or scrapes
  eAccounts, Transact, or any Duke system. All data comes from things you do yourself.
- Card numbers are stored as the last 4 digits only. There are no analytics or trackers.
- "Delete all my data" hard-deletes every row tied to you.
- The shared catalog holds only `(location, item, base_price, add-on, first_seen, last_seen,
  times_seen)`, with day-level dates and no user ids. Contributing is opt-in, and only
  receipt-verified prices are shared.
- `data/` and `out/` (real purchase history) are gitignored. Tests use synthetic fixtures.

## Notes

- The schema is created with `create_all`. There are no migrations yet. After a model change,
  delete `dukedining.db` (or run `make seed`).
- Fonts (Google Fonts), htmx and Chart.js load from version-pinned CDNs for the hackathon. Vendor
  them into `app/static/` before this becomes a real product.
- The term end date for the run-out projection defaults to Dec 18 2026. Override it with
  `DUKEDINING_TERM_END=YYYY-MM-DD`.
