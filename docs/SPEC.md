# thecube: Duke dining coach (build spec)

Last updated 2026-11-07. Hackathon build: 2 people, 24 hours. Building ends 11:00 AM
Sunday, then a 5-minute pitch + 3 minutes Q&A. Judged on: real problem, how much works,
creativity, clarity.

Read with: `docs/findings/receipts.md`, `docs/findings/netnutrition.md`.

## 1. What we're building

An iPhone app that answers **"what should I eat next?"** using:

- **Real menus and macros** from Duke NetNutrition (scraped).
- **What you actually ate and paid**, from Transact mobile-order receipt emails, plus
  manual logging for in-person purchases.
- **Your points balance and meal swipes**, to keep you on pace for the semester.

A Gemini "coach" turns numbers the code computed into a short WHOOP-style card and a
reason for each pick. **Code computes every number; the LLM only writes words.**

## 2. Scope

| In (build this) | Out (do not build) |
| --- | --- |
| NetNutrition scraper → menu DB (core) | eAccounts access of any kind |
| Receipt import: upload `.eml` files, plus Postmark inbound for live forwarding | Screenshot / PDF / Gemini vision import |
| Manual log: pick vendor → pick items from menu → price auto-filled or typed | Combo solver / "guess what you ordered" inbox |
| Points + swipes budget (balance entered by hand) | Statement parsing |
| Next-meal optimizer + Eat Next screen | Gemini goal parsing (use toggles) |
| Coach card + pick reason (Gemini) | History screen, carb mode (stretch only) |
| Diet/allergen filters from NetNutrition traits | Scraping Transact web order (needs login) |
| Two users: William (real data), Blue Devil (fake) | Auth system (bearer token + user picker) |

## 3. Stack and repo

- **Backend:** Python 3.12, FastAPI, Postgres (SQLAlchemy Core or psycopg), deployed on Railway.
- **LLM:** Gemini via `google-genai`. Model from `GEMINI_MODEL` env var, default
  `gemini-3.5-flash-lite`. Alternative: `gemini-3.8-flash` with thinking level low.
  Don't set temperature/top_p (deprecated on current models).
- **iOS:** SwiftUI, Xcode 27, deployment target iOS 27 (iOS 26 if a demo phone isn't on 27).
  Stock components only; Liquid Glass comes for free. No third-party packages.
- **Email:** Postmark inbound (free) POSTs forwarded emails to the backend. Nothing to host.

```
thecube/
  CLAUDE.md                 # instructions for Claude Code
  docs/SPEC.md, docs/findings/*.md
  emails/                   # William's real receipts (.eml); gitignored if repo is public
  spikes/                   # throwaway exploration scripts + outputs
  backend/
    app/main.py, db.py, auth.py, schemas.py
    app/routes/   today.py next_meal.py imports.py menu.py manual.py settings.py admin.py
    app/ingest/   receipt_parser.py  postmark.py  netnutrition.py  matcher.py
    app/core/     budget.py  optimizer.py  macros.py
    app/coach/    gemini.py  prompts.py
    db/schema.sql
    seed/         aliases.json  blue_devil.py  duke_points_fall2026.json
    tests/
  ios/thecube/    Views/ ViewModels/ API/
```

Env vars (backend): `DATABASE_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `APP_TOKEN`,
`POSTMARK_WEBHOOK_USER`, `POSTMARK_WEBHOOK_PASS`, `DEMO_TODAY` (optional, `YYYY-MM-DD`).
Never commit `.env`. iOS reads `API_BASE_URL` and `APP_TOKEN` from a gitignored `Secrets.xcconfig`.

## 4. Data model (`backend/db/schema.sql`)

```sql
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE,                       -- Duke address receipts are sent to / forwarded from
  is_demo BOOLEAN NOT NULL DEFAULT FALSE,
  settings JSONB NOT NULL DEFAULT '{}'     -- Settings model (section 9)
);

-- NetNutrition catalog
CREATE TABLE IF NOT EXISTS nn_units (
  unit_oid INT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'retail'      -- 'retail' | 'dining_hall'
);
CREATE TABLE IF NOT EXISTS nn_items (
  item_oid BIGINT PRIMARY KEY,
  unit_oid INT NOT NULL REFERENCES nn_units(unit_oid),
  course TEXT,                             -- "Choose Protein"
  name TEXT NOT NULL,
  allergens TEXT[] NOT NULL DEFAULT '{}',  -- egg fish gluten milk peanut sesame shellfish soy tree_nut wheat
  diets TEXT[] NOT NULL DEFAULT '{}',      -- halal vegan vegetarian
  ingredients TEXT,
  menu_date DATE,                          -- dining halls only
  meal TEXT,                               -- dining halls only: Breakfast/Brunch/Lunch/Dinner
  scraped_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS nn_portions (
  item_oid BIGINT NOT NULL REFERENCES nn_items(item_oid) ON DELETE CASCADE,
  uofm_oid BIGINT NOT NULL,
  portion_name TEXT NOT NULL,              -- "Burrito Portion"
  is_default BOOLEAN NOT NULL,
  grams REAL,
  calories REAL, protein_g REAL, carbs_g REAL, fat_g REAL,
  fiber_g REAL, sugar_g REAL, sodium_mg REAL,
  PRIMARY KEY (item_oid, uofm_oid)
);

-- Our vendors (receipt names) mapped to NetNutrition units
CREATE TABLE IF NOT EXISTS vendors (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,               -- canonical, e.g. "Sazon"
  building TEXT,
  unit_oid INT REFERENCES nn_units(unit_oid),  -- NULL = no nutrition data (Gothic Grill)
  hours JSONB NOT NULL DEFAULT '{}'        -- {"mon":[["11:00","20:00"]]} local; hand-seeded
);
CREATE TABLE IF NOT EXISTS vendor_aliases (raw TEXT PRIMARY KEY, vendor_id INT NOT NULL REFERENCES vendors(id));
CREATE TABLE IF NOT EXISTS item_aliases (
  vendor_id INT NOT NULL REFERENCES vendors(id),
  raw TEXT NOT NULL,                       -- lowercased receipt name
  item_oid BIGINT NOT NULL REFERENCES nn_items(item_oid),
  PRIMARY KEY (vendor_id, raw)
);

-- What things cost (from receipts and manual entry)
CREATE TABLE IF NOT EXISTS prices (
  vendor_id INT NOT NULL REFERENCES vendors(id),
  item_name TEXT NOT NULL,                 -- receipt item name, e.g. "Burrito"
  variant TEXT NOT NULL DEFAULT '',        -- priced component if any, e.g. "Hot Honey Chicken"
  price NUMERIC(6,2) NOT NULL,
  source TEXT NOT NULL,                    -- 'receipt' | 'manual'
  observed_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (vendor_id, item_name, variant)   -- keep latest
);

-- What the user ate and paid
CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id),
  ts TIMESTAMPTZ NOT NULL,
  vendor_id INT REFERENCES vendors(id),
  vendor_raw TEXT NOT NULL,
  subtotal NUMERIC(6,2), tax NUMERIC(6,2), total NUMERIC(6,2),
  points_spent NUMERIC(6,2) NOT NULL,      -- "Student Food" tender
  swipes_used INT NOT NULL DEFAULT 0,
  swipe_value NUMERIC(6,2) NOT NULL DEFAULT 0,
  source TEXT NOT NULL,                    -- 'email' | 'manual' | 'seed'
  external_ref TEXT,                       -- Transact order number
  raw_email BYTEA,
  macros_partial BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (user_id, external_ref)
);
CREATE TABLE IF NOT EXISTS order_items (
  id SERIAL PRIMARY KEY,
  order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  price NUMERIC(6,2),
  format TEXT                              -- 'burrito' | 'quesadilla' | 'arepa_bowl' | 'taco' | NULL
);
CREATE TABLE IF NOT EXISTS order_components (  -- what macros are computed from
  order_item_id INT NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
  raw_name TEXT NOT NULL,
  item_oid BIGINT REFERENCES nn_items(item_oid),   -- NULL = unmatched
  uofm_oid BIGINT,
  servings REAL NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS balance_snapshots (
  user_id INT NOT NULL REFERENCES users(id),
  ts TIMESTAMPTZ NOT NULL,
  points NUMERIC(8,2) NOT NULL,
  swipes INT,
  PRIMARY KEY (user_id, ts)
);
CREATE TABLE IF NOT EXISTS coach_cache (
  kind TEXT NOT NULL, input_hash TEXT NOT NULL, output JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, input_hash)
);
```

A simple item with no components (e.g. "Salmon Poke Bowl") gets one `order_components`
row pointing at the item itself.

## 5. NetNutrition scraper (`app/ingest/netnutrition.py`)

Follow `docs/findings/netnutrition.md` exactly. Output: upserts into `nn_units`, `nn_items`,
`nn_portions`.

- One `requests.Session`, sequential, `time.sleep(1)` between POSTs, User-Agent
  `thecube-hackathon/0.1 (Duke student project)`.
- For each unit: `SelectUnitFromUnitsList`. If `itemPanel` has items → retail. If `menuPanel`
  has menus → dining hall: take today's menus only, `SelectMenu` each.
- For each item: parse name, course, trait icons, portions. For each portion:
  `ChangeUofM` (skip for the default), then `ShowItemNutritionLabel`, parse the label.
- CLI: `python -m app.ingest.netnutrition --units 18,21 --out spikes/nn.json` and
  `--all --write-db`. Cache raw label HTML in `spikes/nn_cache/<itemOid>_<uofmOid>.html`
  so re-runs and parser fixes don't re-hit the site.
- Admin route `POST /admin/scrape?units=...` runs it in a background task.

## 6. Receipt import

### Parser (`app/ingest/receipt_parser.py`)

Start from `spikes/parse_receipt.py` (works on all 31 receipts). Return:

```python
class ParsedReceipt(BaseModel):
    order_number: str
    placed_at: datetime          # localize America/New_York → UTC
    vendor_raw: str; building: str
    items: list[ParsedItem]      # name, price (effective), components: list[str], priced_component: str|None
    subtotal: float; tax: float; total: float
    points_spent: float          # "Student Food" tender
    swipes_used: int; swipe_value: float
```

Also handle an `.eml` whose attachments are `message/rfc822` receipts (bulk forward):
parse each attachment.

### Two ways in

1. `POST /import/eml` (multipart, one or more files, `user_id`). Used for the backfill
   and in development.
2. `POST /ingest/postmark` (Postmark inbound JSON; basic auth from env). Pick the user by
   the forwarder's address (`From` of the forward, matched to `users.email`). Find the
   original receipt in `HtmlBody` (the forward wraps it) or in `Attachments` (`.eml`, base64).

### Pipeline after parsing

1. Dedup on `(user_id, external_ref)`; skip if exists.
2. Vendor: `vendor_aliases` exact match (lowercased, whitespace collapsed), else
   `rapidfuzz` `token_set_ratio ≥ 85` against `vendors.name` with no other vendor within
   3 points (used for this order, **not** saved as an alias), else `vendor_id NULL`.
   Known vendors come from `seed/aliases.json`. (Changed 2026-11-07 after E3: `WRatio ≥ 85`
   mapped McDonald's → J.B.'s and Devil's Krafthouse → It's Thyme.)
3. Prices: upsert `prices(vendor, item_name, variant=priced_component or '')`.
4. Format from item name (burrito, quesadilla, arepa bowl, taco; else NULL).
5. Components → `item_oid` via `matcher.py`: `item_aliases` exact, else `rapidfuzz`
   `token_set_ratio ≥ 90` within that unit **and** no differently-named item within
   3 points (write the alias), else NULL (reported in `unknown_components`).
   (Changed 2026-11-07 after E3: `≥ 80` auto-wrote "Whole" → Latte Whole Milk and
   "Sweet Potato Chips" → Sweet Potato Fries.)
   Portion: the item's portion whose name contains the format keyword (burrito /
   quesadilla / arepa / taco; names vary: "Arepa Bowl Portion", "Arepa Portion", "Arepa"),
   else default.
6. `macros_partial = true` if any component is unmatched or vendor has no unit.
7. Return `{imported, duplicates, partial: [order numbers], unknown_components: [...]}`.

## 7. Manual log (in-person purchases)

`POST /orders/manual` with `{user_id, vendor_id, ts, items:[{item_oid, uofm_oid, servings}], points_spent?, swipes_used?}`.

- App flow: pick vendor → browse that unit's NetNutrition items by course (macros
  visible, tap for full label) → add items → price shown if `prices` has one for that
  vendor/item, else a "price" field → save.
- Typed prices are written to `prices` with `source='manual'`.
- `points_spent` defaults to the sum of prices × 1.075 tax, editable.

## 8. Budget (`app/core/budget.py`)

```python
def status(user, today):
    snap = latest balance_snapshot for user
    points = snap.points - sum(o.points_spent for orders after snap.ts)
    swipes = snap.swipes - sum(o.swipes_used ...) if snap.swipes is not None else None
    days_left = max((semester_end - today).days, 1)
    daily_budget = points / days_left
    spent_today = sum(points_spent today)
    trailing = sum(points_spent over previous 7 full days) / 7
    runout = today + floor(points / trailing) days if trailing > 0 else None
    runout = None if runout >= semester_end else runout
    return PointsStatus(points, swipes, days_left, daily_budget, spent_today, runout, on_pace = trailing <= daily_budget)
```

"Today" = local date in America/New_York, overridable by `DEMO_TODAY`.

**Duke pace (added 2026-11-07):** if `settings.meal_plan` is set, `status` also returns
`meal_plan`, `pace_target` = Duke Dining's Fall 2026 points chart value for that plan today
(`seed/duke_points_fall2026.json`, linear between the chart's weekly rows; 0 from Dec 14) and
`vs_pace = points - pace_target` (negative = behind). The coach gets the gap pre-computed.
Semester end defaults to 2026-12-14 (the chart's end date).

## 9. Settings (per user, toggles only)

```python
class Settings(BaseModel):
    semester_end: date
    targets: Targets            # calories (min 1800), protein_g
    goal: Literal["balanced", "build_muscle", "budget"] = "balanced"
    require_diets: list[Literal["halal", "vegan", "vegetarian"]] = []
    avoid_allergens: list[Literal["egg","fish","gluten","milk","peanut","sesame","shellfish","soy","tree_nut","wheat"]] = []
    show_calories: bool = True
    meal_plan: Literal["A","B","C","D","E","F","I","J"] | None = None   # Duke plan, for the pace chart
```

## 10. Next-meal optimizer (`app/core/optimizer.py`)

Candidates are **priced meals at vendors with NetNutrition data**:

- **Simple items:** any `prices` row whose item_name matches an `nn_items` name at that unit.
- **Build-your-own templates:** per vendor, a seeded template, e.g. Sazon Burrito =
  1 base + 1 protein + up to 3 toppings + 1 sauce, at `prices` for that protein. Generate
  combos from the menu (cap ~200 per vendor), using the format's portion.

Then:

1. Keep vendors open now (`vendors.hours`); none open → open within 2 hours.
2. Drop candidates where any component violates `require_diets` (every component must
   carry the diet) or contains an `avoid_allergens` trait. No trait data = excluded when a
   restriction is set.
3. Per-meal targets: remaining meals = 1 after 5 PM else 2; protein and calorie gaps ÷ meals.
4. `headroom = daily_budget - spent_today`.
5. Score: `-1.0*|p - p_t|/max(p_t,1) - 0.6*|cal - c_t|/max(c_t,1) - 1.5*max(0, price - headroom)/max(headroom,1) + 0.2*history_share`.
   Bias `protein` → protein weight 1.6. Bias `cheap` → price weight 3.0.
6. Return the top 3 across at least 2 vendors when possible.

Implementation notes (T9, 2026-11-07; `app/core/optimizer.py`, templates in `seed/templates.json`):
- **Vegan counts as Halal and Vegetarian.** NetNutrition tags Halal only on meats, so a
  literal "every component carries halal" removed every bowl (rice, salsa are Vegan only).
- A pick must cover ≥ 30% of the per-meal calorie target (otherwise an over-budget user
  is offered a $3 yogurt cup as a "meal").
- Bias `protein` penalizes only falling short of the protein target, not exceeding it.
- At most one pick per template per vendor (picks differ by more than the protein).
- Vendor hours are real (NetNutrition `Unit/GetHoursOfOperationMarkup`), seeded in
  `seed/aliases.json`.

**Scoring (revised 2026-11-07):** each bias optimizes a different objective; prices are
scaled by `ref_price = max(daily_budget / 2, 8)` (a typical meal), not by today's headroom
(a nearly spent day made every option equally bad, so all tabs agreed):
balanced = -1.2 short - 0.6 extra - 0.8 cal_dev - 0.35 over - 0.25 cost;
protein = 2.0 min(protein / target, 1.5) - 0.3 cal_dev - 0.15 over - 0.1 cost;
cheap = -2.0 cost - 0.5 over - 0.8 short - 0.2 cal_dev; all + 0.1 history_share
(short/extra = protein below/above target, relative; over = cost above headroom / ref_price).
The app labels the target "Still to eat today" when one meal is left.

## 11. Coach (`app/coach/`)

Same as before; unchanged in spirit:

- **System rules:** use only numbers in the input; direct, no emoji; goals are about
  eating enough and making points last; never praise restriction or use guilt; no calorie
  talk if `show_calories` is false; headline ≤ 60 chars, message ≤ 280.
- **Recap card** (`/today`): input = today's macros vs targets, 7-day protein-hit count,
  points status (incl. swipes). Output `{headline, message, tone: praise|nudge|warning}`.
- **Pick reason** (`/next-meal`): input = top 3 picks + headroom + restrictions in words.
  Output `{chosen_index, headline, reason}`.
- JSON schema output. Number check: every number in the output must appear in the input,
  else retry once, else template fallback. Cache by input hash.

## 12. API

All routes need `Authorization: Bearer $APP_TOKEN` and take `user_id` (query or body),
except `/ingest/postmark` (basic auth).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/users` | List users (William, Blue Devil) for the app's user switcher |
| GET | `/today?user_id=` | Macros eaten vs targets, points status, coach card, today's meals |
| GET | `/next-meal?user_id=&bias=` | 3 picks + coach choice + reason |
| GET | `/vendors` | Vendors with unit, open now, has_nutrition |
| GET | `/vendors/{id}/menu` | NetNutrition items by course with portions, macros, traits, known price |
| POST | `/orders/manual` | Manual log |
| DELETE | `/orders/{id}` | Remove a mistaken log |
| POST | `/import/eml` | Upload receipts |
| POST | `/ingest/postmark` | Live forwarding |
| GET/PUT | `/settings?user_id=` | Toggles, targets, semester end |
| POST | `/balance` | `{user_id, points, swipes}` snapshot |
| POST | `/admin/scrape` | Run scraper |
| POST | `/admin/reset-demo` | Rebuild Blue Devil; re-import William from `emails/` |

## 13. iOS app

Four tabs plus a user switcher (William / Blue Devil) in the toolbar.

| Tab | Shows | Actions |
| --- | --- | --- |
| Today | Coach card; protein + calorie rings (calories hidden if off); points left, swipes left, daily budget, run-out date; today's meals | Pull to refresh; swipe a meal to delete (`swipeActionsContainer()` on iOS 27) |
| Eat next | 3 picks: vendor, items, price, protein/cal/carbs; coach pick highlighted with reason | Segmented: Balanced / More protein / Cheaper |
| Log | Vendor list → menu by course → item rows with macros and trait icons → tap for full label | Add items, enter price if unknown, save; "Import receipts" button (`.fileImporter` for `.eml`) |
| Settings | Goal, targets, diet + allergen chips, show calories, semester end, balance entry | Save |

While Today is visible, poll `/today` every 5 s (so a live-forwarded receipt appears on stage).

## 14. Demo data

- **William (real):** all receipts in `emails/` imported. Balance snapshot entered by hand.
  The live demo is William forwarding a real new receipt from Outlook.
- **Blue Devil (fake, renamed from Jordan):** `seed/blue_devil.py`, deterministic
  (`random.seed(42)`), 28 days of orders **built from real scraped NetNutrition items and
  real receipt prices**. Story: upperclass Plan A, goal build_muscle (2,800 cal / 150 g
  protein), short on protein most weekdays (2 of 7 days), 135 points behind Duke's Plan A
  chart, so at the current pace points run out Dec 5 (9 days before Dec 14). Today:
  breakfast + lunch logged, 74 g protein. No restrictions at start; the demo toggles
  Halal + Peanut live.
- **Live forward lands on Blue Devil:** Blue Devil's `users.email` is William's Duke
  address, so the receipt William forwards on stage shows up on Blue Devil's Today.
- `POST /admin/reset-demo` restores both exactly.

## 15. Build order

### Phase 0: exploration (Claude Code, normal mode)

| ID | Task | Done when |
| --- | --- | --- |
| E1 | Run the NetNutrition flow from Python (`spikes/netnutrition_spike.py`) for Sazon (18) and Marketplace (4) | JSON with items, traits, portions and parsed labels; confirm cookie/token needs |
| E2 | Run full scrape for the 8 units William uses; save to `spikes/nn.json` | Coverage report: for each receipt component, matched / unmatched |
| E3 | Matching report: run receipts × menu through rapidfuzz | List of mismatches to seed into `item_aliases`; % of orders with full macros |

### Phase 1: core (A = backend, B = iOS)

| ID | Owner | Build | Done when |
| --- | --- | --- | --- |
| T1 | A | Repo skeleton, schema, auth, `/users`, Railway deploy | 401 without token; `/users` returns 2 |
| T2 | A | Scraper into DB (from E1/E2) | `nn_items` populated for target units |
| T3 | A | Receipt parser + `/import/eml` + matcher + prices | All 31 import; re-import = 31 duplicates; parsed points match receipts |
| T4 | B | Xcode project, models, APIClient, Today on mock JSON | Renders in simulator |
| T5 | A | Budget + `/today` (coach null) | Unit tests on sample numbers |
| T6 | A | `/vendors`, `/vendors/{id}/menu`, `/orders/manual` | Manual order for Sazon burrito computes macros |
| T7 | B | Log tab (vendor → menu → add → price → save) | Logged meal shows on Today |
| T8 | A | Blue Devil seed + reset-demo | Two resets identical |
| T9 | A | Optimizer + `/next-meal` | Halal + peanut set → no violating picks |
| T10 | B | Eat next tab | Bias switch changes picks live |
| T11 | B | Coach (3 functions, number check, fallback, cache) wired in | 10 runs, no blank cards |
| T12 | A | Postmark inbound | Forwarding a receipt from Outlook lands within 30 s |
| T13 | B | Settings tab + user switcher | Toggling Halal changes Eat next |
| T14 | Both | Rehearsal from reset-demo | Two clean timed runs |

Stretch after T14: history screen, carb-per-meal mode, dining-hall daily menus.

## 16. Pitch demo (5 minutes)

1. Problem (0:40): points run out, meals suffer, dietary needs ignored.
2. Live (2:30): William forwards a real receipt → it appears with macros → Today coach
   card → switch to Blue Devil → Eat next → "More protein" → toggle Halal + Peanut → picks
   change → log an in-person meal from the menu.
3. How it works (0:40): NetNutrition + receipts → Postgres → code computes → Gemini words.
4. Impact (0:40): Transact + CBORD run dining at many campuses.

Be explicit about what's real (menus, William's receipts, live email) vs fake (Blue Devil).
