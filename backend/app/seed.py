"""Create the schema and seed base rows. Idempotent.

  cd backend && ../.venv/bin/python -m app.seed [--demo]
"""
import email
import sys
import json
from email import policy
from email.utils import getaddresses
from pathlib import Path

from app.db import connect, init_schema
from app.schemas import Settings

ROOT = Path(__file__).resolve().parents[2]
EMAILS = ROOT / "emails"

# Placeholders until each user sets them in the app (Settings tab / T13).
SEMESTER_END = "2026-12-14"   # Duke Dining's Fall 2026 points chart counts down to Dec 14
WILLIAM = Settings(semester_end=SEMESTER_END, targets={"calories": 2400, "protein_g": 120})
BLUE_DEVIL = Settings(semester_end=SEMESTER_END, targets={"calories": 2800, "protein_g": 150},
                      goal="build_muscle", meal_plan="A")  # SPEC 14 story


def william_email() -> str | None:
    """The address William's receipts were sent to (his Duke address)."""
    for p in sorted(EMAILS.glob("*.eml")):
        msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
        addrs = [a for _, a in getaddresses([str(msg["To"] or "")]) if a]
        if addrs:
            return addrs[0].lower()
    return None


def seed_users(conn) -> None:
    """William (real receipts) and Blue Devil (demo student). William's Duke address belongs to
    Blue Devil, so a receipt William forwards live during the pitch lands on Blue Devil's Today."""
    conn.execute("UPDATE users SET name = 'Blue Devil' WHERE name = 'Jordan'")  # renamed 2026-11-07
    rows = [("William", False, WILLIAM), ("Blue Devil", True, BLUE_DEVIL)]
    for name, demo, settings in rows:
        conn.execute(
            """INSERT INTO users (name, is_demo, settings)
               SELECT %s, %s, %s WHERE NOT EXISTS (SELECT 1 FROM users WHERE name = %s)""",
            (name, demo, json.dumps(settings.model_dump(mode="json")), name))
    addr = william_email()
    if addr:
        conn.execute("UPDATE users SET email = NULL WHERE name <> 'Blue Devil' AND lower(email) = %s", (addr,))
        conn.execute("UPDATE users SET email = %s WHERE name = 'Blue Devil'", (addr,))


ALIASES = ROOT / "backend" / "seed" / "aliases.json"


def seed_vendors(conn, path: Path = ALIASES) -> list[str]:
    """Vendors, vendor_aliases, item_aliases from aliases.json. Run after the scrape (T2):
    item aliases are stored by name and resolved here to the newest matching item_oid, so
    re-running after each scrape re-points them (dated-menu units change OIDs).
    Returns warnings for anything that couldn't be resolved."""
    from app.ingest.matcher import key
    data = json.loads(path.read_text())
    known_units = {r["unit_oid"] for r in conn.execute("SELECT unit_oid FROM nn_units").fetchall()}
    warnings, ids = [], {}
    for v in data["vendors"]:
        unit = v["unit_oid"] if v["unit_oid"] in known_units else None
        if v["unit_oid"] is not None and unit is None:
            warnings.append(f"vendor {v['name']}: unit {v['unit_oid']} not scraped yet; unit_oid left NULL")
        ids[v["name"]] = conn.execute(
            """INSERT INTO vendors (name, building, unit_oid, hours) VALUES (%s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET building = EXCLUDED.building, unit_oid = EXCLUDED.unit_oid,
                 hours = EXCLUDED.hours
               RETURNING id""", (v["name"], v["building"], unit, json.dumps(v.get("hours", {})))).fetchone()["id"]
        for raw in v["aliases"]:
            conn.execute("""INSERT INTO vendor_aliases (raw, vendor_id) VALUES (%s, %s)
                            ON CONFLICT (raw) DO UPDATE SET vendor_id = EXCLUDED.vendor_id""", (key(raw), ids[v["name"]]))
    units = {v["name"]: v["unit_oid"] for v in data["vendors"]}
    for vname, aliases in data["items"].items():
        for raw, target in aliases.items():
            name, course = (target, "") if isinstance(target, str) else (target["name"], target.get("course", ""))
            row = conn.execute(
                """SELECT item_oid FROM nn_items WHERE unit_oid = %s AND name = %s AND course LIKE %s
                   ORDER BY menu_date DESC NULLS LAST, scraped_at DESC, item_oid LIMIT 1""",
                (units[vname], name, f"%{course}%")).fetchone()
            if not row:
                warnings.append(f"item alias {vname}/{raw!r} -> {name!r}: not in nn_items")
                continue
            conn.execute("""INSERT INTO item_aliases (vendor_id, raw, item_oid) VALUES (%s, %s, %s)
                            ON CONFLICT (vendor_id, raw) DO UPDATE SET item_oid = EXCLUDED.item_oid""",
                         (ids[vname], key(raw), row["item_oid"]))
    return warnings


def main() -> None:
    with connect() as conn:
        init_schema(conn)
        seed_users(conn)
        warnings = seed_vendors(conn)
        c = conn.execute("""SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM vendors) AS vendors,
                                   (SELECT count(*) FROM vendor_aliases) AS vendor_aliases,
                                   (SELECT count(*) FROM item_aliases) AS item_aliases""").fetchone()
    for w in warnings:
        print("warning:", w)
    print("seeded:", dict(c))
    if "--demo" in sys.argv:  # also import William's receipts and build Blue Devil (= /admin/reset-demo)
        from app import demo
        with connect() as conn:
            print("demo:", demo.reset(conn))


if __name__ == "__main__":
    main()
