# Pitch plan (Sunday 11 AM: 4 min pitch + demo, 1 min Q&A)

Judges score **real problem**, **how much works after 24 h**, **creativity**, **clarity**; also
Best Social Impact and Judge's Choice. Q&A answers are in `QA.md`. The forwarding address is in
`RUNBOOK.md` (gitignored).

**Shape:** slides → live app → slides. Open on the problem (judges need the "why" before the
app means anything), show the app for almost half the time, close on impact. Two people:
**A = Story** (talks over slides, owns the clock) and **B = Driver** (runs the app and talks
during the demo). A third teammate runs the slide clicker and holds up 1-minute / 30-second
cards to A.

## The 4 minutes

| Time | Who | Screen | Say |
| --- | --- | --- | --- |
| 0:00–0:20 | A | Slide 1 (title) | "Hands up if you know whether your food points will last until December 14." (pause) "First semester, nobody does. You find out during finals." Pause. "Duke puts menus in one place and your balance in another. Nothing tells you if you'll make it." |
| 0:20–0:50 | A | Slide 2 (receipt → app) | "Pitchfork: forward your Duke receipt email. We log the meal with Duke's own nutrition data, check your points against the Registrar calendar, and tell you what to eat next. No Duke login, nothing scraped from your account." |
| 0:50–2:40 | B | Slide 3 dark → simulator | Live demo, 1:50, beats below. A says nothing. |
| 2:40–3:15 | A | Slide 4 (numbers) | "Every number is computed by code. The AI only writes the sentences, and any sentence with a number we didn't compute is thrown out. 527 real Duke dishes, 31 of 31 real receipts read right, zero Duke logins, and the real Fall 2026 calendar: 104 dining days, breaks skipped. 63 automated tests." |
| 3:15–3:50 | A | Slide 5 (Know now, not Dec 9) | "Running out of points means skipping meals during finals. Pitchfork tells you now, with a month to fix it, not on December 9. Next: auto-forward rules, push nudges, and any school on NetNutrition." |
| 3:50–4:00 | A | Slide 5 | "We're Pitchfork. Questions?" |

### Demo beats (B, 1:50)

Start on Today, scrolled to the top. Blue Devil is a made-up student with real Duke menus and
real prices.

1. **Today (0:30).** "This is Blue Devil." Read the coach card: *runs out December 9, before
   the semester ends.* Point at the protein ring. Scroll to Points: *135 behind*, then the
   orange line: **"Spend N points less a day and they last through Dec 14."** (N changes daily; read what it shows) "That one line
   is the whole app: one number you can act on."
2. **Eat next (0:30).** Scroll back up. Read the pick and its reason. Tap **More protein**:
   "it only suggests places open now, inside your points for today." (Before 11 AM it shows
   "Sazon, opens 11:00"; say "opens in a few minutes".)
3. **Feeling hungry (0:20).** Tap the card, tap the pan, the card flips. "For when you don't
   want to think." Close.
4. **Wrapped (0:20).** Devil → Your Wrapped. Tap 3 slides: spot, protein in eggs, personality.
5. **Widgets (0:10).** Swipe home: "same numbers, without opening the app." Hand back to A.

If anything hangs for more than 3 seconds, B says "here's the recording" and plays the backup
video from the same beat. Don't debug on stage.

## Q&A (1 minute: one answer each, 15 seconds max)

A takes "why / who / impact" questions; B takes "how does it work" questions. Likely ones:

- **"Is the data real?"** (B) Menus, macros, prices and the calendar are real; Blue Devil's
  history is generated from them. Forwarding was tested with 7 real Outlook forwards.
- **"Why not read eAccounts directly?"** (A) No public API, and we won't ask for students'
  Duke passwords. A receipt they already get is consent by design.
- **"What if an item isn't on NetNutrition?"** (B) Points still count; the meal is marked
  partial, never guessed.
- **"How do you make money / scale?"** (A) Free for students; Duke Dining or student
  government could run it. Any school on NetNutrition works with a new calendar file.

## Slides (5)

Rule: the slides are pictures; the talking is ours. No subtitles, no bullets, no sentence that
we're also saying out loud. If a slide needs a caption to make sense, the picture is wrong.

1. **Pitchfork.** The name, "Will your food points last?", the widget on a phone, team names small.
2. **Receipt → app.** A real Sazon receipt, "forward" on an arrow, the Today screen.
3. *(Demo.)* Feeling hungry and Wrapped on two phones: a backdrop, and the fallback if the demo dies.
4. **The numbers.** Four big numbers, one or two small words under each: **527** menu items ·
   **31/31** receipts read right · **0** Duke logins · **104** days on the calendar. No title.
5. **Know now, not Dec 9.** That line, the devil. Done.

Assets in `design/slides/`: `logo.png`, `devil.png` (transparent), `today.png`, `hungry.png`,
`wrapped.png`, `widgets_home.png`, `widget_large.png`. **Still to make:** the receipt email
screenshot (from Outlook, address blurred), and a fresh `today.png` taken Sunday ~10:45 so it
shows the new coach card and a pick.

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
6. Two full timed run-throughs, A and B together. Target 3:50. Eat next lists places open now; before 11 AM on
   Sunday it shows "Sazon, opens 11:00" (that's correct, not a bug).

## Gemini's audit: what we did with it

| Finding | Verdict | Done |
| --- | --- | --- |
| Calorie target hits 0 after a big day → sauces become the "best" pick | **Real and visible on stage** (a judge logs a meal) | Fixed: scoring uses at least a 20 g / 400 cal meal; the shown target stays true |
| `demo_reset` fails on a brand-new database | Only matters on a fresh deploy; we demo on the existing local DB | Not touched |
| Bowl entrée not counted when a receipt lists toppings | Real: a forwarded poke bowl counted 4 g protein | Fixed: hand-checked "includes" list in `seed/aliases.json` adds the salmon, teriyaki chicken, tortilla, egg + cheese |
| Feeling hungry calls `/next-meal` 3× (3 coach calls) | Coach is cached per input; loads in about a second | Not touched |
| Wrapped 500s for a user with orders but no items | Can't happen for Blue Devil | Not touched |
| Widget has no App Group / mock data | Widgets read the server directly; they work (screenshots) | Not touched |
| Pace off by a day on Dec 14, no DB indexes, Postmark retry on malformed mail, `{}` settings default, old spike files | Real, invisible tomorrow | Not touched |

Also fixed tonight: the toolbar devil dropped taps (its animation rebuilt the button every
frame). It's now a still sprite with a native menu (Feeling hungry / Wrapped). Feeling hungry
has its own card on Today and cooks on a tap, not only a hold.
