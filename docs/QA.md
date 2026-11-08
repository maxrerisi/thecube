# Judge Q&A prep

Short answers first; detail after the dash if they push. Keep this updated as we build.
See `PRODUCT.md` for how everything works.

## "Doesn't this already exist?"

- **Duke NetNutrition** shows nutrition facts per item. It doesn't know what *you* ate,
  doesn't add up your day, and doesn't recommend anything.
- **Menu apps** show menus and nutrition. You still do the math and the logging.
- **MyFitnessPal-style trackers** don't know Duke's menus or your points; you log every meal by hand.
- **eAccounts / DukeCard** shows your balance, but not whether it'll last or what to do about it.
- **Us:** logging is automatic (forward the receipt), macros come from Duke's own data,
  points are checked against the real semester calendar, and it tells you what to eat next
  within your goal, diet and budget. Nobody joins those three.

## Data

**Where do macros come from?** Duke NetNutrition, the official public nutrition site. We
scrape it politely (1 request/second, cached): 527 items at 9 locations.

**Did you fake the nutrition?** No. Every macro comes from a NetNutrition label. If a receipt
line can't be matched (e.g. McDonald's isn't on NetNutrition), the meal is marked "partial"
rather than guessed.

**How accurate is the matching?** All 31 real receipts parse. Lines are matched by aliases,
then fuzzy name matching within that vendor. Known gap: burrito/quesadilla receipts don't list
the tortilla, so those undercount by roughly 290 calories.

**Why not use Duke's dining API?** There isn't a public one. Balances and transactions live in
Transact eAccounts behind NetID + MFA. We didn't scrape it (fragile, and not ours to scrape).
Receipt forwarding gives us the same data with the student's consent.

**Where does "pace" come from?** Duke's published Fall 2026 starting balance for the plan
(Plan A 3,071.28), spread evenly over the 104 days you actually eat on campus per the
Registrar calendar (Aug 24 – Dec 14, minus fall break and Thanksgiving). Duke's own chart
ignores breaks; ours doesn't.

**Is Blue Devil real?** No. A made-up student with real menus and real prices. Their history
is generated so the story is clear: behind pace, short on protein.

## AI

**What does the AI do?** It writes the coach sentences and the one-line reason for the pick.
That's it.

**Can it hallucinate numbers?** Every number in its output must appear in the numbers our code
gave it, or the output is rejected and we retry, then fall back to a fixed template. It also
can't mention calories when the user turned them off.

**Why not let the AI pick the meal?** Picking is math: protein, calories, price, budget,
restrictions. Code does it the same way every time and we can test it.

## Product

**How does the recommendation work?** For each place open now, it builds possible meals from
the menu, drops anything violating diet/allergens, and scores what's left for the chosen goal
(Balanced / More protein / Cheaper) against what you still need today and your points room.

**What if nothing's open?** It shows places opening within 2 hours, labeled with the time.

**What about dining-hall swipes?** Receipts record swipes used; the Points card shows swipes
left. The pace math is about points.

**Privacy?** The student chooses what to forward. We store their receipts and settings,
nothing else; no Duke login. In production: per-user forwarding addresses, delete-my-data.

## Tech

**Stack?** SwiftUI iPhone app; Python FastAPI + Postgres server; Postmark for inbound email;
Gemini flash-lite for words.

**How does the email get to the app?** Forward → Postmark turns it into a web request → our
server parses and saves it → the app polls every 5 seconds.

**Does it scale?** The scrape is shared by every user (menus are the same for everyone). Per
user it's a few rows per meal. The coach is cached per input, so repeated views are free.

**Tested?** 5 iPhone UI tests that tap every button through iOS's real touch system, 3 times each. 62 backend tests: receipt parsing on all 31 receipts, duplicate forwarding, pace
and breaks, optimizer goals produce different picks, coach validation. Plus a scripted
rehearsal of the demo (forward → Today → picks → restrictions → log → Wrapped, ~7 s).

## Delight features

**What's Feeling hungry?** Our "I'm feeling lucky": tap (or hold) the pan, a pick flips over, swipe for
another. Same optimizer picks, just a faster way to decide when you don't care which goal.

**Is Wrapped made up by the AI?** No. Every stat (meals, top spot, signature order, protein,
peak hour, personality) is a SQL/Python computation; the AI only writes the caption, and a
caption with any number not in that slide's facts is rejected.

**Why a pixel devil?** Duke Blue Devils, and it shows status at a glance: sleepy before you eat,
happy when protein is hit, sweating when you're behind on points.

**Widgets?** Lock screen protein ring and points-pace bar; home screen pick with an "Another"
button that rerolls without opening the app.

## Limits (say them before they ask)

- One user, demo-grade auth (one shared token).
- Balance is typed in, not read from DukeCard.
- Burrito/quesadilla tortillas are missing from receipts.
- Dated menus (It's Thyme, Tandoor, Trinity) change daily; we cache what we scraped.
- Runs on a laptop with a tunnel for the demo, not hosted.

## Future

Per-student forwarding addresses; auto-forward rules so there's no manual step; spring term
calendar; push nudges ("you're 135 behind, Cheaper tab tonight?"); other schools on NetNutrition (it's a common vendor
product).
