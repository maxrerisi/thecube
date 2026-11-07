# Transact / eAccounts: can we read Duke dining data directly?

Researched 2026-11-07. No logins, no authenticated endpoints; four requests total to public
Transact pages (robots.txt, page, config.js, JS bundle) plus one to Duke's portal landing page.

## What Duke uses

- **DukeCard balances and transactions: Transact eAccounts.** Duke's tenant is
  `https://duke-sp.transactcampus.com/eAccounts/AnonymousHome.aspx` (linked from
  dukecard.duke.edu). In the Transact eAccounts app you pick "Duke University", then
  "Duke eAccounts Portal". You sign in with NetID, password and Duke MFA (Shibboleth SSO).
  Transaction history is visible in the portal and the app.
- **Mobile ordering: Transact Mobile Ordering** (app id 1494719529; web version at
  `weborder.transactcampus.com/<campusid>`). You select "Duke University" and sign in with
  NetID.
- **Not CBORD GET.** Some schools run CBORD's GET (`get.cbord.com/GETServices/...`); Duke
  doesn't, so open-source GET balance readers don't apply.

So the institution is located: the eAccounts tenant is `duke-sp`. The web-order campus id is
unconfirmed (see the next section).

## What the earlier repo attempt did (origin/main, origin/mvp)

- `bd0a891 init` (Max): `main.py` used Playwright to render
  `https://weborder.transactcampus.com/7` (a Transact Web Order "Locations" page, campus id 7)
  and saved `output.html`. The saved page is only the React shell plus CSS: no Duke text, no
  data. It stopped there.
- `6ec62ff`: "Remove Transact scraper ... conflicted with the no-scraping constraint."
- The mvp line then switched to **user-supplied eAccounts data**: `dukedining/eaccounts.py`
  parses the Account Transactions table that a student copies from the eAccounts page, or a
  CSV of it. Columns: Date/Time, Account Name, Card Number, Location, Transaction Type,
  Amount. Locations look like `Gothic Grill GOTWeb1` / `Its Thyme THYKsk1`; the suffix tells
  web order vs register vs kiosk. DEMO.md on that branch shows "paste the eAccounts table,
  type the balance".

## Public institution lookup?

- **eAccounts app:** the school picker shows only schools that subscribe to eAccounts and
  enable mobile (Transact FAQ). I found no documented public institution-list endpoint, and I
  did not probe the app's private API.
- **Web Order:** `weborder.transactcampus.com/config.js` is public and names the API base
  `https://mobileorderprodapi.transactcampus.com/api_weborder/`. The bundle calls endpoints
  like `locations`, `getmenu`, `menuslots` and `samllogin?campusid=`.
  - Every call carries headers `campusid`, `sessionid`, `uuid` and a **`hash`**: a checksum of
    endpoint + uuid + campusid + ... computed with a key embedded in the JS.
  - Calling it ourselves would mean reproducing that signature, i.e. working around their
    request signing. I stopped there and did not call the API.
  - I could not confirm that campus id 7 is Duke. The page is client-rendered, and no public
    page links that URL to Duke.

## What a logged-in student could get

From the eAccounts portal or app, after NetID + MFA:
- the current Food points balance
- full transaction history (time, location/terminal, account, amount)

There is no API for students; it's an ASP.NET web portal behind Duke SSO. Automating it would
mean a headless browser holding the student's NetID session through MFA. That is fragile, a
credential/ToS problem, and exactly what the team already ruled out. I found no maintained
open-source eAccounts/Transact scraper. The GitHub hits for "balance scraper" are bank
scrapers.

The supported path is what the mvp branch built: the student exports or copies the
transaction table themselves.

## What works / uncertain

- Works:
  - Duke's tenant is identified (`duke-sp.transactcampus.com`).
  - Receipt emails (our approach) already cover itemized purchases.
  - An eAccounts copy-paste or CSV import (mvp branch code) would cover balance and
    non-itemized charges, with zero integration.
- Uncertain:
  - whether web-order campus 7 is Duke
  - whether Transact offers partner/institution API access, which would need Duke Dining or
    Transact as a partner
  - whether the eAccounts statement can be exported as CSV directly (the mvp code expects a
    paste of the table)

## Recommendation (hackathon)

- **Don't use Transact for the demo.** No public API; the web-order API is request-signed, and
  eAccounts sits behind NetID SSO + MFA. Any scraping risks breaking live, and it raises
  ToS/credential questions judges may ask about.
- **Slide: "Future: direct integration."** Duke already runs Transact (eAccounts + Mobile
  Ordering) and Transact powers 1,000+ campuses. With a Duke Dining / Transact partnership,
  balances and transactions would arrive automatically, replacing the typed-in balance.
- **Cheap middle ground if time allows:** port the mvp branch's eAccounts paste parser, so a
  student pastes their transaction table once to set their balance and backfill history.
  It's user-supplied data, so no scraping.
