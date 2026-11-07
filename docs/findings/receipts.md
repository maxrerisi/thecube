# Findings: Transact mobile-order receipt emails

Explored 2026-11-07 against 31 real receipts in `emails/` (Aug 21 – Oct 25, 2026).
Parser: `spikes/parse_receipt.py` (stdlib only). Output: `spikes/receipts.json`.

## Result

31/31 parsed with no errors. For every receipt, item prices sum to the subtotal and
tenders sum to the total. A deterministic parser is enough; no LLM is needed for email.

## Format

- **Sender:** `Duke University <mobileorder@transactcampus.com>` (all 31).
- **Subject:** `#<order number> Receipt`.
- **Body:** `multipart/alternative`. Both parts contain the same HTML table. Parse the HTML part.
- **Header rows** (centered, single cell), in order:
  1. `#<order number>`
  2. placed time, local, e.g. `2026-10-25 4:17 PM` (America/New_York)
  3. `Target: 4:29 PM` (pickup time)
  4. vendor name, e.g. `Sazon`
  5. building, e.g. `Brodhead Center`
  6. street address
  7. `Duke University`
- **Item rows:** `<b>N. Item Name</b>` with the price in the right cell.
- **Component rows:** indented with 8 `&nbsp;` under their item (sauces, proteins, toppings).
  Up to 17 per item for build-your-own.
- **Price location varies:** for some build-your-own items (Sazon Arepa Bowl, Quesadilla,
  Burrito) the item row has an empty price and the price sits on the **protein component**
  (e.g. `Hot Honey Chicken $12.85`). Effective item price = item price, else sum of component prices.
- **Totals:** `Subtotal`, `Tax`, `Total`.
- **Tenders** (after `DukeCard`):
  - `Student Food  $x.xx` = food points actually spent.
  - `Board Plan Equivalency $11.80 | 1 Used - $11.80` = a meal swipe. Seen values:
    $11.80 (Its Thyme) and $6.10 (The Skillet, breakfast). 11 of 31 orders used a swipe.
- **Notes:** free-text lines like `Cutlery Needed`, `BAG ITEMS - TO-GO`, `GO GREEN - EAT-IN`. Ignore.
- **Trailer:** `Transaction #  <same as order number>`.

## Consequences for the app

1. **Points spent = the `Student Food` tender, not the total.** Using the total overstates
   spend on every swipe order.
2. **Track meal swipes separately** (count and dollar equivalency per order).
3. **Tax is 7.5% on the points-paid portion only.** Swipe orders show tiny tax
   (e.g. $0.01). Don't infer tax from the subtotal.
4. **Order number is a perfect dedup key** (unique, in subject and body).
5. **Vendor names differ from NetNutrition** (`Its Thyme` vs `It's Thyme`,
   `Tandoor` vs `Tandoor Indian Cuisine`, `Ginger & Soy` vs `Ginger + Soy`,
   `Farmstead  &  Sprout Sandwiches` vs `The Farmstead`/`Sprout`). Needs an alias table.
6. **Component names differ slightly** (`Plaintains` vs `Maduros (Sweet Plantains)`,
   `Super Food Lettuce` vs `Super Food Salad Mix`, `Fajita Peppers and Onion` vs
   `Fajita Peppers and Onions`). Fuzzy match plus a manual alias table.

## Vendors in this data

| Vendor (receipt) | Building | Orders | On NetNutrition? |
| --- | --- | --- | --- |
| The Skillet | Brodhead Center | 6 | Yes (8) |
| Its Thyme | Bryan Center | 5 | Yes, "It's Thyme" (21) |
| Ginger & Soy | Brodhead Center | 4 | Yes, "Ginger + Soy" (19) |
| Sazon | Brodhead Center | 4 | Yes (18) |
| The Devil's Krafthouse | Brodhead Center | 3 | **No** |
| Gothic Grill | Bryan Center | 3 | **No** |
| Tandoor | Brodhead Center | 2 | Yes, "Tandoor Indian Cuisine" (16) |
| Trinity | East Campus Union | 1 | Yes, "Trinity Cafe" (5) |
| Farmstead & Sprout Sandwiches | Brodhead Center | 1 | Likely "The Farmstead" (11) / "Sprout" (10) |
| Gyotaku | Brodhead Center | 1 | Yes (20) |
| McDonald's | Bryan Center | 1 | **No** |

7 of 31 orders (23%) are at vendors with no NetNutrition data. Macros for those are
"unknown" unless the user enters them.

## Other surfaces checked

- `weborder.transactcampus.com/7` (the existing `main.py`): renders "No available
  locations" without login. Menus and prices are not public there. Don't pursue.
- Prices: receipts give real prices for everything William has ordered. For anything
  else, the user types the price once (manual import) and it's saved.

## Getting more receipts

In Outlook on the web, search `mobileorder@transactcampus.com`, select all, and either
download each as `.eml` or forward all as attachments in one email. The importer should
accept a single `.eml` and also an `.eml` whose attachments are `message/rfc822` receipts.
