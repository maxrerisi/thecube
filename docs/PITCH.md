# Pitch plan (Sunday, 5 min + 3 min Q&A)

Judges score four things: **real problem**, **how much works after 24 h**, **creativity**, and
**clarity**. They also pick Best Social Impact and Judge's Choice. Every minute below is aimed at
one of those. Q&A answers are in `QA.md`. The forwarding address and setup are in `RUNBOOK.md`
(gitignored).

## The 5 minutes

| Time | What | Who / screen | Scores |
| --- | --- | --- | --- |
| 0:00–0:30 | **Hook.** "Hands up if you've run out of food points, or come close, before finals." Duke shows menus in one place and your balance in another; nothing tells you if you'll make it or what to eat. | Slide 2 | Problem |
| 0:30–0:45 | **One line.** "Forward your receipt. Pitchfork logs the meal with Duke's own nutrition data, checks your points against the Registrar calendar, and tells you what to eat next." | Slide 3 | Clarity |
| 0:45–1:15 | **How logging works** (slide, not live). "You already get a receipt email for every mobile order. Forward it; the meal lands in your log on the day you bought it, with macros from NetNutrition. No Duke login, no scraping your account." | Slide 4 | Problem, works |
| 1:15–3:15 | **Live demo** (2:00, see below) | Simulator, mirrored | Works, creativity |
| 3:15–3:55 | **Why trust it.** "Code computes every number; the AI only writes the sentences, and anything with a number we didn't compute is rejected. A line we can't match is marked partial, never guessed." | Slide 5 | Clarity, works |
| 3:55–4:30 | **Real, not mocked.** 527 NetNutrition items, all 31 real receipts parse, Fall 2026 calendar with breaks, 62 tests. Built since 11 AM yesterday. | Slide 6 | Works |
| 4:30–5:00 | **Next + close.** Per-student addresses, auto-forward rules, push nudges, any school on NetNutrition. "Nobody should find out on Dec 9 that they can't eat for finals week." | Slide 7 | Impact |

### Demo, beat by beat (2:00)

One account in the app: Blue Devil, a made-up student with real Duke menus and real prices.
No live forwarding on stage; it's on slide 4.

1. **Today (0:30).** The devil is sweating. Read the coach card: *135 points behind, runs out
   Dec 9, the first day of finals.* Point at the protein ring (74 of 150 g) and today's two
   meals ("these came in as forwarded receipts").
2. **Eat next (0:30).** Balanced pick, then tap **More protein**: the pick changes. "It only
   suggests places open right now, inside your points for today."
3. **Feeling hungry (0:25).** Tap the card, tap the pan, the card flips. One line: "for when
   you don't want to think."
4. **Wrapped + widgets (0:35).** Open Wrapped from the devil, tap 2–3 slides (signature order,
   protein in eggs). Swipe home: widgets show the same numbers without opening the app.

## Slides (7, mostly pictures)

1. **Title.** `logo.png` + `devil.png`, "Pitchfork: your Duke dining coach", team names.
2. **Problem.** Three short lines: *NetNutrition knows the food. eAccounts knows your balance.
   Nothing knows you.* Below: "Points run out before finals; there's no public dining API."
3. **What it does.** `today.png` beside the one-liner.
4. **How logging works.** Left to right: the Duke receipt email (screenshot one from Outlook,
   blur the address) → "Forward" → Postmark → our server (parse, match to NetNutrition) → the
   meal in the log, on the day it was bought. One line under it: "Tested with real Outlook
   forwards: 7 of 7 read correctly."
5. **Why trust it.** "Code does the math. AI writes words, and is checked." Plus the
   "partial, never guessed" rule.
6. **Real data.** Four big numbers: **527** menu items · **31/31** receipts parse · **104**
   dining days (breaks skipped) · **62** tests. Small: `hungry.png`, `wrapped.png`,
   `widget_large.png` as a strip.
7. **What's next.** Per-student addresses and auto-forward; push nudges; spring calendar;
   other NetNutrition schools. Big devil.

Assets in `design/slides/`: `logo.png`, `devil.png` (transparent, scales crisply), `today.png`,
`hungry.png`, `wrapped.png`, `widgets_home.png`, `widget_large.png`. For the pipeline, draw 5
boxes in the slide tool; it's faster than an image and easier to read.

## Who does what

- **Presenter:** talks, drives the simulator (mirror the Mac screen).
- **Slides:** whoever isn't the presenter flips slides, or put them in the same window.

## On your iPhone

Phone builds talk to this Mac through the Cloudflare tunnel (the `[sdk=iphoneos*]` line in
`ios/Config/Secrets.xcconfig`), so anything forwarded shows up on the phone too. If the server
can't be reached (no Wi-Fi, laptop asleep, tunnel restarted), every screen falls back to a
snapshot of the demo data bundled in the app (`ios/Shared/Mock/`, refreshed tonight), so the
phone always has something to show. Writes (logging a meal) need the server.

Install: plug in and unlock the iPhone (Developer Mode on), then

    xcodebuild -project ios/thecube.xcodeproj -scheme thecube -destination 'generic/platform=iOS' -derivedDataPath ios/build-device -allowProvisioningUpdates build
    xcrun devicectl device install app --device <iPhone UDID> ios/build-device/Build/Products/Debug-iphoneos/thecube.app

If `cloudflared` restarts, its URL changes: update that line and the Postmark webhook, then
rebuild. Add the widgets from the home screen once it's installed.

## Testing the buttons

`ios/thecubeUITests` taps through iOS's real touch system: the Feeling hungry card, the devil
menu to Feeling hungry and to Wrapped, the Wrapped card, the goal switch and all three tabs,
three times each. Passes against the live server and with the server unreachable.

    xcodebuild test -project ios/thecube.xcodeproj -scheme thecubeUITests -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max'

It takes about 4 minutes and doesn't log meals, so no reset is needed after it.

## Morning checklist (by 10:30)

1. Server running, tunnel running (`cloudflared` URL changes on restart → update the Postmark
   webhook, see RUNBOOK).
2. `cd backend && ../.venv/bin/python scripts/demo_reset.py`. Run it **after** any rehearsal or
   test forward; they add meals. It rebuilds Blue Devil (the only account).
3. Open the app on Today; check: sweating devil, ~135 behind, Dec 9. Numbers shift a little day
   to day; read them off the screen rather than reciting.
4. Laptop on power, Do Not Disturb on, notifications off, simulator at a readable zoom.
5. **Backup video**: record one clean run tonight (`xcrun simctl io booted recordVideo demo.mp4`).
   If the Wi-Fi or tunnel dies on stage, play it and narrate.
6. One full timed run-through. Target 4:45. Eat next lists places open now; before 11 AM on
   Sunday it shows "Sazon, opens 11:00" (that's correct, not a bug).

## Gemini's audit: what we did with it

| Finding | Verdict | Done |
| --- | --- | --- |
| Calorie target hits 0 after a big day → sauces become the "best" pick | **Real and visible on stage** (a judge logs a meal) | Fixed: scoring uses at least a 20 g / 400 cal meal; the shown target stays true |
| `demo_reset` fails on a brand-new database | Only matters on a fresh deploy; we demo on the existing local DB | Not touched |
| Bowl entrée not counted when a receipt lists toppings | Duke receipts put the protein in the priced component, so demo meals are right; known gap is the tortilla (in QA "Limits") | Not touched |
| Feeling hungry calls `/next-meal` 3× (3 coach calls) | Coach is cached per input; loads in about a second | Not touched |
| Wrapped 500s for a user with orders but no items | Can't happen for Blue Devil | Not touched |
| Widget has no App Group / mock data | Widgets read the server directly; they work (screenshots) | Not touched |
| Pace off by a day on Dec 14, no DB indexes, Postmark retry on malformed mail, `{}` settings default, old spike files | Real, invisible tomorrow | Not touched |

Also fixed tonight: the toolbar devil dropped taps (its animation rebuilt the button every
frame). It's now a still sprite with a native menu (Feeling hungry / Wrapped). Feeling hungry
has its own card on Today and cooks on a tap, not only a hold.
