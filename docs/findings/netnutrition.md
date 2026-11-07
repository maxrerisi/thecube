# Findings: Duke NetNutrition

Explored 2026-11-07 in a real browser at https://netnutrition.cbord.com/nn-prod/Duke.
Public, no login. An old ASP.NET MVC app: every action is a jQuery `POST` that returns
JSON containing HTML fragments ("panels"). There is no clean JSON API; parse the HTML.

The flow was later verified from plain Python on a Mac (E1, below).

## Request flow

Base: `https://netnutrition.cbord.com/nn-prod/Duke`. All POSTs are
`application/x-www-form-urlencoded`. The server keeps state in the ASP.NET session cookie,
so use one `requests.Session` and do calls **sequentially**.

| Step | Request | Body | Returns |
| --- | --- | --- | --- |
| 0 | `GET /nn-prod/Duke` | | Sets session cookie. Home HTML lists units: `onclick="NetNutrition.UI.unitsSelectUnit(<unitOid>)"` with the unit name as link text |
| 1 | `POST /nn-prod/Duke/Unit/SelectUnitFromUnitsList` | `unitOid=18` | `{success, panels:[{id, html}]}`. Retail units: `itemPanel` has the item list. Dining halls (e.g. Marketplace, 4): `menuPanel` has a menu list instead |
| 1b | `POST /nn-prod/Duke/Menu/SelectMenu` | `menuOid=9517377` | Dining halls only. Menu list items are `menuListSelectMenu(<menuOid>)` grouped under a date heading ("Saturday, November 7, 2026") with meal names (Brunch, Dinner). Returns `itemPanel` |
| 2 | `POST /nn-prod/Duke/Menu/ChangeUofM` | `detailOid=<itemOid>&uofmOid=<uofmOid>` | Sets the serving size for that item **in the session**. Do this before step 3 for each non-default portion |
| 3 | `POST /nn-prod/Duke/NutritionDetail/ShowItemNutritionLabel` | `detailOid=<itemOid>` | HTML nutrition label for the item at the session's current serving size |

Other endpoints seen (not needed): `Menu/SelectTrait` (allergen/diet filters, session state),
`Menu/ChangeUofM` (above), hours modal per unit (`openHoursInModal(<unitOid>)`).

## Units (21)

| unitOid | Name | unitOid | Name |
| --- | --- | --- | --- |
| 6 | Bella Union | 15 | Red Mango |
| 9 | Bseisu Coffee Bar | 13 | Saladalia @ The Perk |
| 12 | Cafe | 14 | Sanford Deli |
| 2 | Duke Marine Lab | 18 | Sazon |
| 3 | Freeman Café (kosher) | 10 | Sprout |
| 19 | Ginger + Soy | 16 | Tandoor Indian Cuisine |
| 20 | Gyotaku | 11 | The Farmstead |
| 17 | Il Forno | 8 | The Skillet |
| 21 | It's Thyme | 5 | Trinity Cafe |
| 7 | J.B.'s Roast & Chops | 22 | Zweli's Café at Duke Divinity |
| 4 | Marketplace (dining hall, dated menus) | | |

Missing vendors William uses: The Devil's Krafthouse, Gothic Grill, McDonald's.

## Item panel structure

- Courses: elements with `onclick="NetNutrition.UI.toggleCourseItems(this, <courseId>)"`;
  text is the course name. Sazon: Desserts; Build Your Own ... (Choose One); Choose Base;
  Choose Protein; Choose Topping; Choose Sauce; Choose Sides.
- Each item is a `<tr data-categoryid="<courseId>">` containing:
  - `a#showNutrition_<itemOid>`: first text node = item name.
  - `img` tags inside that link: `title` = trait. Allergens: Egg, Fish, Gluten, Milk,
    Peanut, Sesame, Shellfish, Soy, Tree Nut, Wheat. Diets: Halal, Vegan, Vegetarian
    (Sustainable also exists as a filter).
  - `select#uofm<itemOid>`: serving sizes; `option value` = uofmOid, text = portion name,
    `selected` = default. Example Chipotle Chicken: Taco Portion (3061330, default),
    Arepa Bowl Portion (8244578), Quesadilla Portion (8244577), Burrito Portion (8244579).
- Sazon: 46 items. Rows with `style="display:none"` are just collapsed courses; still parse them.

## Nutrition label

Text after stripping tags, e.g. Chipotle Chicken:

- Taco Portion (142g): 220 cal, fat 10 g, sat fat 2.5 g, cholesterol 155 mg,
  sodium 410 mg, carbs 3 g, fiber < 1 g, sugars < 1 g, protein 29 g, plus ingredients.
- Burrito Portion (94g): 150 cal, fat 6 g, carbs 2 g, protein 19 g.

**Portion changes macros by about 50%, so store per-portion nutrition.** Parse with regexes:
`Serving Size\s*(.+?)\s*\((\d+)g\)`, `Calories\s*(\d+)`, `Total Fat\s*([\d.<]+)g`,
`Total Carbohydrate\s*([\d.<]+)g`, `Protein\s*([\d.<]+)g`, `Sodium\s*([\d.<]+)mg`,
`Dietary Fiber\s*([\d.<NA]+)`, `Total Sugars\s*([\d.<NA]+)`. Treat `< 1` as 0.5 and `NA` as null.
Keep the ingredients string (useful for allergen display).

## Mapping receipts to NetNutrition

Build-your-own receipts list components; NetNutrition lists the same components as items
with a portion per format. To compute macros for a receipt item:

1. Map receipt vendor → unitOid (alias table).
2. Derive the format from the receipt item name: Burrito → "Burrito Portion",
   Quesadilla → "Quesadilla Portion", Arepa Bowl → "Arepa Bowl Portion", Taco → "Taco Portion".
3. For each component, fuzzy-match to an item in that unit, take the portion matching
   the format (else the default), sum macros.
4. For simple items (e.g. "Salmon Poke Bowl"), match the item name directly at its
   default portion.
5. Unmatched components are listed as "unknown" with zero macros, and the order is marked
   `macros_partial`.

## Scale and politeness

About 21 units × ~50 items × ~2.5 portions ≈ 2,500 label requests. At 1 request/second
that's ~45 minutes for a full scrape. Retail menus rarely change: scrape once and cache;
re-scrape dining-hall menus daily. Send a descriptive User-Agent.

## Verified from Python (E1, 2026-11-07)

`spikes/netnutrition_spike.py` now runs end to end from a plain Python process on a Mac
(`requests` 2.34, in `.venv`). Sazon (18) and Marketplace (4) scrape with 0 problems.

```
.venv/bin/python spikes/netnutrition_spike.py 18 4 --out /tmp/nn.json
```

Answers to the old open questions:

- **Cookies and token:** a plain `requests.Session` works. `GET /nn-prod/Duke` sets
  `ASP.NET_SessionId`, `AWSALB`/`AWSALBCORS` (load-balancer stickiness) and
  `CBORD.netnutrition2=NNexternalID=Duke`. There is **no anti-forgery token**: the home page
  has no `__RequestVerificationToken`, and no POST asked for one. `X-Requested-With:
  XMLHttpRequest` is sent (as jQuery does) but was not tested without it.
- **`menuOid` on the label call:** not needed. A Marketplace label fetched with and without
  `menuOid` was identical. Retail items don't pass it at all (the JS's `onclick` passes only
  `detailOid`). The spike passes it for dining halls anyway, since that's what the browser does.

What broke in the browser-written spike, and the fixes:

1. **Quotes.** Panel HTML uses single-quoted attributes (`data-categoryid='4'`,
   `id='uofm303709897'`, `onclick='...toggleCourseItems(this, 4);'`). The old regexes required
   `"`, so the first run parsed 0 items without an error. Regexes now accept either quote.
2. **Single-portion items have no `uofm` select.** About 60% of Sazon items and 99% of
   Marketplace items (317/321) have one fixed serving, shown as plain text in the third
   cell (e.g. "Brownie", "2 oz Serving"). There is no uofmOid in the HTML. The spike stores
   them with `uofm_oid = 0` and fetches the label without `ChangeUofM`. **Schema note:**
   `nn_portions.uofm_oid` is `NOT NULL`, so 0 works as written; no schema change needed.
3. **Session state.** `ChangeUofM` returns `{"success":true,"panels":[]}` and only changes
   the server session, so the label call depends on (a) which unit/menu is selected and
   (b) the last size set *for that item*. The old code skipped `ChangeUofM` for the default
   portion, which breaks if any other size was set first. The spike now always calls
   `ChangeUofM` for items that have a select, and re-selects the unit/menu before the first
   uncached label (so cached runs don't leave the session pointing at the wrong unit).
4. **Check that labels match the request.** Every label's `Serving Size` is compared with the
   requested portion name. 0 mismatches across all scraped units (see E2), so the session
   handling is right.
5. **Dining halls.** `menuPanel` holds `<header class='card-title'>Saturday, November 7,
   2026</header>` cards, each with `menuListSelectMenu(<menuOid>)` links named by meal. On
   2026-11-07 Marketplace listed **only today** (Brunch 9517377, Dinner 9517378), so a future
   day's menu can't be scraped ahead of time. `SelectMenu` returns an `itemPanel` with the same
   structure as retail. **Item OIDs are per menu:** 321 item OIDs but only 207 distinct
   names, so the same dish has different OIDs at Brunch and Dinner. Store them as separate
   `nn_items` rows (which `menu_date`/`meal` already allows) and dedup by name in the UI.

Label details: `Dietary Fiber NA` and `Trans Fat NA` occur; fiber/sugar come back null then.
`< 1g` parses as 0.5. Saturated fat, cholesterol, calcium, iron and potassium are on the label
but not in the schema (not needed).

Caching: labels in `spikes/nn_cache/<itemOid>_<uofmOid>.html` (kept forever), unit panels
in `unit_<unitOid>_<date>.json`, dining menus in `menu_<menuOid>.json`, home in
`home_<date>.html`. A re-run of a cached unit makes 0 requests. Requests are spaced
≥ 1 s apart by a monotonic clock, sequentially.

Traits are split into `allergens` / `diets` per SPEC 4 (lowercased, `tree_nut`); anything
else (e.g. Sustainable) goes in `other_traits`.

## Full scrape of William's units (E2, 2026-11-07)

```
.venv/bin/python spikes/netnutrition_spike.py 8 21 19 18 16 5 20 11 10 --out spikes/nn.json
```

9 units, 527 items, 698 portions, **746 requests in ~13 min, 0 serving-size mismatches**,
no errors or throttling. Per-unit counts are in `docs/findings/matching.md`.

- **"Retail" units can have dated menus.** It's Thyme (21), Tandoor (16) and Trinity Cafe
  (5) return a `menuPanel`, not an `itemPanel`, exactly like Marketplace. The SPEC 5 rule
  ("menuPanel → dining hall") labels them `dining_hall`. Their menus are only today's
  (Saturday: It's Thyme 35 items with no acai bar, Tandoor 20). Item OIDs change per menu,
  so anything keyed by item_oid (`item_aliases`, `order_components`) can point at an
  old row after the next scrape. Old rows must be kept (FKs), so scraping should upsert,
  never delete.
- Portion names are not standardized even within a unit ("Arepa Bowl Portion" / "Arepa
  Portion" / "Arepa" / "Portion"); some labels are for a whole batch (It's Thyme White Rice
  "Batch" 8,500 cal; Trinity Iced Chai Oat "Batch" 5,120 cal), so outliers need a sanity cap.
- The same name can appear in several courses with different portions (Gyotaku "Salmon":
  0.6 oz sashimi vs 3 oz bowl), and in both topping and side courses at Sazon.

## What works

- Plain `requests` session, no token, 1 req/s, sequential. Retail and dated-menu units.
- Every label matches the requested serving; macros parse for all 698 portions.
- Cache makes re-runs free.

## What's uncertain

- Whether dated-menu units list other days on weekdays (only today was shown on a Saturday).
- `X-Requested-With` was always sent; untested without it.
- Batch-sized labels and `NA` fields (null fiber/sugar/protein in a few sauces).

## Recommendation

Port the spike as-is into `app/ingest/netnutrition.py` (T2). Store `kind` by the SPEC rule
but treat "has dated menus" separately from "dining hall" in the UI (It's Thyme is a
retail counter). Re-scrape dated-menu units daily, upsert by item_oid, and resolve
aliases by name after each scrape (see `matching.md`).
