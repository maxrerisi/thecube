# Findings: matching receipts to NetNutrition (E2 + E3)

Run 2026-11-07 (a Saturday). Inputs: 31 receipts (`spikes/receipts.json`, from
`spikes/parse_receipt.py emails/`) × `spikes/nn.json` (9 units scraped in E2).
Script: `spikes/match_receipts.py`; per-line detail in `spikes/matching.json`.

```
.venv/bin/python spikes/match_receipts.py spikes/receipts.json spikes/nn.json backend/seed/aliases.json
```

## E2: what was scraped

| unit | name | items | portions | menu type |
| --- | --- | --- | --- | --- |
| 8 | The Skillet | 56 | 59 | fixed |
| 21 | It's Thyme | 35 | 35 | **dated** ("All Day", "Dinner") |
| 19 | Ginger + Soy | 141 | 141 | fixed |
| 18 | Sazon | 46 | 119 | fixed |
| 16 | Tandoor Indian Cuisine | 20 | 20 | **dated** ("Lunch/Dinner") |
| 5 | Trinity Cafe | 93 | 188 | **dated** ("Specialty Drinks", ...) |
| 20 | Gyotaku | 115 | 115 | fixed |
| 11 | The Farmstead | 15 | 15 | fixed |
| 10 | Sprout | 6 | 6 | fixed |

527 items, 698 portions, 746 requests (~13 min), 0 label/serving mismatches.

## Method (SPEC 6 as written)

- **Line** = what macros come from: each component, or the item itself if it has no
  components. 137 lines in 31 orders; 12 are at vendors with no NetNutrition unit
  (Gothic Grill, McDonald's, The Devil's Krafthouse).
- Vendor: `vendor_aliases` exact, else `WRatio ≥ 85`. Component: `item_aliases` exact,
  else `token_set_ratio ≥ 80` within the unit. Labels: **ok** ≥ 90; **low** 80–89;
  **ambiguous** = a differently-named item scores within 3 points; **unmatched** < 80.
- Portion: the portion whose name contains the format keyword (burrito / quesadilla /
  arepa / taco), else default. Keyword, not "Burrito Portion": Sazon alone uses "Arepa Bowl
  Portion", "Arepa Portion", "Arepa" and "Portion".
- Tie-break on equal scores: prefer an item that has a portion for the format (topping
  "Pico de Gallo" over side "Pico de Gallo"), then plain `ratio`.

## Result

| | Lines matched (at vendors with a unit) | Orders with full macros |
| --- | --- | --- |
| Fuzzy only (SPEC rules, no aliases) | 74 / 128 (58%) | 8 / 31 (26%) |
| With proposed `aliases.json` | **92 / 125 (74%)** | **12 / 31 (39%)** |

With no aliases, WRatio assigned **The Devil's Krafthouse → It's Thyme (85.5)** and
**McDonald's → J.B.'s Roast & Chops (85.5)**, and "Ranch"/"Honey mustard" were then
matched against It's Thyme's menu. Vendor fuzzy matching at 85 is not safe; see recommendations.

"Full" overstates accuracy. Of the 12 "full" orders:
- 4 Ginger + Soy poke-bowl orders show **4–6 g protein**: the salmon is the *item*
  ("Salmon Poke Bowl"), the receipt components are only rice and sauces, and SPEC counts
  only components when an item has any.
- 2 Skillet "Biscuit Egg Cheese with Protein" orders count only the bacon; the biscuit,
  egg and cheese are in the item name.
- The Sazon burrito lists no tortilla; the 12" flour tortilla (290 cal) is missing.

### Unmatched / low / ambiguous, with best candidate (after aliases)

| Vendor | Receipt name | Best candidate (score) | Why |
| --- | --- | --- | --- |
| It's Thyme | Traditional Acai ×4 | Avocado (44) | Acai bar not on Saturday menu |
| It's Thyme | Honey Oat Granola ×4, Honey Drizzle ×4, Seasonal Berries ×4 | Roasted Tomatoes (49), White Rice (52), Burmese Tofu (43) | same |
| It's Thyme | Sliced Banana ×3, Chia Pudding, Sunbutter, Diced Pineapple, Candied Cranberries | Pickled Jalapenos (53), Cajun Pinto Beans (41), Cucumbers (44), White Rice (48), Brown Rice and Quinoa (45) | same |
| It's Thyme | Basil Roasted Potatoes | Roasted Tomatoes (74); real: Oven Roasted Potato Medley (67)? | not on today's menu |
| It's Thyme | Sweet Potato Chips — **low, wrong** | Sweet Potato Fries (83) | passes ≥ 80 but is a different item (dinner side) |
| Tandoor | Tofu Korma | Tofu Malabar (64) | menu rotates daily |
| Tandoor | $5 Meal Deal (no components) | Masala Dosa (55) | deal contents unknown |
| The Skillet | Mac and Cheese | Cheddar Cheese Slice (60) | not on Skillet's NN (Farmstead has Macaroni and Cheese) |
| The Skillet | Fair Life Strawberry Milk ×2 | Strawberries (49) | packaged drink, not on NN |
| Sazon | Pickled onions ×2 | Fajita Peppers and Onions (60) | not on current menu |
| Trinity | Regular Espresso | Red Eye (44) | drink modifier |
| Trinity | Vanilla | Cappuccino Oat Milk (39) | syrup modifier |
| Trinity | Whole — **ambiguous, wrong** | Latte Whole Milk (100) = Steamer Whole Milk (100) | milk modifier; subset match picks a Large latte (+340 cal) |

Fixed by aliases (were unmatched/ambiguous under fuzzy only): Monterrey Jack Cheese,
Super Food Lettuce, Plaintains, Chimichurri, Fresco Sour cream, Habanero (tied coleslaw
vs hot sauce at 100), Chicken (tied every chicken at 100), Grilled Chicken, Chips and
Pico de gallo, Sausage (Sausage Gravy vs Pork Sausage Patty at 100), Salmon / Sushi Rice /
Edamame at Gyotaku (several courses, different portions), Pickles, Iced Latte, Sub Brioche
Bun (85, low), Full Stack.

Container item names never match and don't need to: Burrito, Quesadilla, Arepa Bowl,
$5 Meal Deal, Build Your Own Bowl, Acai Thyme, Sashimi Bowl, Pancake Breakfast, Latte.

## Proposed `backend/seed/aliases.json`

Written. 12 vendors (9 with units, 3 with `unit_oid: null`), 17 vendor aliases,
32 item aliases across 6 vendors. Item values are a NetNutrition name, or `{name, course}`
where the same name appears in several courses with different portions (Gyotaku "Salmon"
is 0.6 oz as sashimi, 3 oz in the Sashimi Bowl). All 32 resolve against `nn.json`.
Guesses (marked `?` in `_notes`): Sazon chicken / grilled chicken → Chipotle Chicken,
chips and pico de gallo → Chips and Salsa, Gyotaku pickles → Pickled Radish.

"Farmstead & Sprout Sandwiches" → The Farmstead (11): its only component, Tangy Bourbon
Chicken, is a Farmstead entree.

## What works

- Parser + scraper data line up: every resolved alias hits a real item; format portions
  are found for every Sazon component.
- Exact and near-exact names (most of Sazon, Ginger + Soy, Gyotaku) match at 100.
- Aliases fix all naming differences in William's history.

## What's uncertain

- **Dated menus** (It's Thyme, Tandoor, Trinity) only list today. Their item OIDs are per
  menu, so `item_aliases.item_oid` will point at stale rows after the next scrape, and
  anything not served today (the whole acai bar) can't be matched at all.
- **token_set_ratio ≥ 80** treats word subsets as 100: "Chicken", "Whole", "Habanero",
  "Sausage" all tie, and auto-writing those as aliases (SPEC 6 step 5) would make the
  wrong guess permanent. "Sweet Potato Chips" → "Sweet Potato Fries" (83) passes wrongly.
- **Items with components lose the item's own food** (poke bowl salmon, biscuit).
- Burrito/quesadilla tortilla isn't on the receipt.
- Modifiers with no NN item (milk, syrup, espresso) mark orders partial forever.
- "Full Stack" is probably 4 pancakes; `item_aliases` has no portion, so it gets 2.

## Recommendation

Use `aliases.json` as the T3 seed. **Status (2026-11-07):** 1 and 2 approved and applied
(SPEC 6 steps 2 and 5, `backend/app/ingest/matcher.py`); 5's re-resolve-by-name is done by
re-running `python -m app.seed` after a scrape. 3 and 4 still need a decision.

1. Vendor fuzzy: don't auto-create a vendor alias from fuzzy; leave `vendor_id NULL` and
   report it (all 12 known vendors are seeded). If fuzzy stays, use `token_set_ratio ≥ 85`,
   which got all 9 real vendors right and rejected all 3 missing ones in this data.
2. Component fuzzy: auto-write an alias only when score ≥ 90 **and** no other name ties;
   otherwise leave `item_oid NULL` and report it in `unknown_components`.
3. Items with components: also match the item name, and add it as a component if it
   matches (aliases already map Salmon Poke Bowl → Marinated Salmon, Tokyo (Teriyaki
   Chicken) → Grilled Teriyaki Chicken).
4. Burrito/quesadilla: add the tortilla as an implicit component (template, SPEC 10 already
   has per-vendor templates).
5. Keep alias targets by *name* (as in `aliases.json`) and re-resolve to item_oid after
   every scrape, so dated-menu units don't go stale. Re-scrape It's Thyme, Tandoor and
   Trinity on a weekday to capture the acai bar and rotating dishes.
