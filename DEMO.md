# 2-minute demo

Everything shown is **synthetic** (`scripts/seed_demo.py` invents a student named Jordan). No real
purchase data is used.

## Before you go on

```bash
make demo
```

This resets `dukedining.db`, seeds Aug 15 – Nov 1, and serves the app at http://localhost:8000.

Have these ready:
- Finder open at `demo/live/` (5 receipt emails from Nov 2–6)
- `demo/live/eaccounts_table.tsv` open in a text editor, all selected and copied (it's the full
  eAccounts table, so it overlaps what's already loaded)
- Balance to type in: **240.34**

To rehearse again, run `make demo` again.

## Script

**0:00 · The problem (Dashboard)**
> "eAccounts tells you *Il Forno ILFReg1, $13.38*. It doesn't tell you what you ate, or that
> you're about to run out."

Point at:
- **$341.89** with the **data complete ✓** stamp: every transaction since the first deposit adds
  up to the balance eAccounts shows.
- **$71.64/week**, and **runs out Dec 3**, about 15 days before finals.
- **94% of spending itemized.** Mobile orders are matched to their receipts by time and amount.

**0:20 · Import (Import tab)**
1. Drag the 5 `.eml` files from `demo/live/` onto the drop zone.
2. Paste the eAccounts table. Type **240.34** as the current balance.
3. Click **Import & match**.

> "No passwords, no scraping. You forward or drag your own emails and paste your own table."

The summary shows **5 new receipts**, **9 new transactions (110 already had)**, and **5 need your
review**. Re-pasting the whole table never double-counts.

**0:50 · Review (the centerpiece)**
1. **Bseisu Coffee Bar, $5.75.** Nothing matches. Press **S** to skip: "I don't remember, and
   that's fine."
2. **Commons, $9.12.** Choose **Something else**, type `Pasta Bar`, and leave the price blank.
   The app uses $8.48, which is the charge minus 7.5% tax to the exact cent. Confirm.
   → **"Saved. That also figured out 1 other charge."** The Nov 4 Commons charge now has a match.
3. **Il Forno, $13.38.** *Meatballs & Spaghetti* or *Chicken Alfredo*? Both are $12.45, and
   past receipts have each one 4 times. Press **2** for Chicken Alfredo, then Enter.
4. **Il Forno again (Nov 5).** Chicken Alfredo is now listed first, because the app learned your
   habit. Confirm.

**1:35 · Back to the Dashboard**
- Balance **$240.34 ✓**: the new import still reconciles.
- **Runs out Nov 26.** The pace picked up, so it now runs out a week sooner.
- Top items and spend by place now include Pasta Bar and the Il Forno answers.

**1:50 · Trust (Privacy tab)**
> "Card numbers are kept as the last 4 digits only. No NetID, no automation of Duke systems, no
> trackers. Delete all my data really deletes it. Sharing prices with the community catalog is
> opt-in, and shared rows carry only place, item, price, and the day."

## If something goes wrong
- Blank dashboard: the seed didn't run. Run `make seed`, then reload.
- Review queue is empty: you already answered everything. Run `make demo` again.
