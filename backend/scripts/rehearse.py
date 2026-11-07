"""T14 rehearsal: run the SPEC 16 live demo against a server, timed, checking each step.

  ../.venv/bin/python scripts/rehearse.py --base http://localhost:8000   (or the Railway URL)

Steps mirror the pitch: reset -> William forwards a receipt (Postmark) -> it lands ->
Today coach card -> switch to Blue Devil -> Eat next -> More protein -> Halal + Peanut -> picks
change, none violate -> log an in-person meal -> it shows on Today. Exit 1 on any failure.
Needs APP_TOKEN, POSTMARK_WEBHOOK_USER/PASS (backend/.env).
"""
import argparse
import email
import os
import sys
import time
from email import policy

import requests

from demo_reset import load_env, reset


class Run:
    def __init__(self, base, token):
        self.base, self.h, self.steps, self.ok = base, {"Authorization": f"Bearer {token}"}, [], True

    def get(self, path, **params):
        r = requests.get(f"{self.base}{path}", headers=self.h, params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def step(self, name, fn):
        t = time.perf_counter()
        try:
            detail = fn()
            ok = True
        except Exception as e:  # noqa: BLE001 - report and continue so one run shows every problem
            detail, ok = f"{type(e).__name__}: {e}", False
        ms = (time.perf_counter() - t) * 1000
        self.ok &= ok
        self.steps.append((name, ok, ms))
        print(f"  {'PASS' if ok else 'FAIL'} {ms:7.0f} ms  {name}: {detail}")
        return detail if ok else None


def outlook_forward(path) -> dict:
    """A Postmark inbound payload for an Outlook 'Forward' of this receipt, from William."""
    m = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    html = m.get_body(("html",)).get_content()
    inner = html.split("<body>", 1)[-1].rsplit("</body>", 1)[0]
    body = (f"<html><body><div>fwd</div><hr><div><b>From:</b> {m['From']}<br><b>Subject:</b> {m['Subject']}</div>"
            f"{inner}</body></html>")
    to = email.utils.parseaddr(str(m["To"]))[1]
    return {"From": to, "FromFull": {"Email": to}, "Subject": f"FW: {m['Subject']}", "HtmlBody": body,
            "TextBody": "fwd", "Attachments": []}


def rehearse(base, token) -> Run:
    run = Run(base, token)
    state = {}
    pm_auth = (os.environ.get("POSTMARK_WEBHOOK_USER", ""), os.environ.get("POSTMARK_WEBHOOK_PASS", ""))

    def do_reset():
        out = reset(base, token, hold_back=1)
        state["held"] = out["held_back"][0]
        users = run.get("/users")
        state["william"] = next(u["id"] for u in users if u["name"] == "William")
        state["devil"] = next(u["id"] for u in users if u["name"] == "Blue Devil")
        return f"blue devil {out['reset']['blue_devil']['orders']} orders, william {out['import']['imported']} imported, holding {state['held']}"

    def forward():
        from demo_reset import EMAILS
        r = requests.post(f"{base}/ingest/postmark", json=outlook_forward(EMAILS / state["held"]), auth=pm_auth, timeout=60)
        r.raise_for_status()
        j = r.json()
        assert j.get("status") == "ok" and j.get("imported") == 1, j
        return f"imported 1 for user {j['user_id']}"

    def william_today():
        t = run.get("/today", user_id=state["william"])
        assert t["coach"]["headline"], t["coach"]
        return f"coach ({t['coach']['source']}): {t['coach']['headline']!r}"

    def devil_today():
        t = run.get("/today", user_id=state["devil"])
        state["devil_meals"] = len(t["meals"])
        assert t["coach"]["headline"] and t["points"]["runout"], t
        return (f"{t['eaten']['protein_g']:.0f} g protein, runs out {t['points']['runout']}, "
                f"coach: {t['coach']['headline']!r}")

    def eat_next(bias):
        def f():
            n = run.get("/next-meal", user_id=state["devil"], bias=bias)
            assert n["picks"], "no picks"
            state[bias] = [p["title"] for p in n["picks"]]
            c = n["coach"]
            return f"{len(n['picks'])} picks; coach: {n['picks'][c['chosen_index']]['title']!r} ({c['source']})"
        return f

    def restrictions():
        s = run.get("/settings", user_id=state["devil"])
        s.update(require_diets=["halal"], avoid_allergens=["peanut"])
        r = requests.put(f"{base}/settings", params={"user_id": state["devil"]}, json=s, headers=run.h, timeout=30)
        r.raise_for_status()
        n = run.get("/next-meal", user_id=state["devil"], bias="protein")
        titles = [p["title"] for p in n["picks"]]
        assert titles and titles != state["protein"], "picks did not change"
        menus = {}
        for p in n["picks"]:  # check every component's traits against the vendor's menu
            if p["vendor_id"] not in menus:
                m = run.get(f"/vendors/{p['vendor_id']}/menu")
                menus[p["vendor_id"]] = {i["item_oid"]: i for c in m["courses"] for i in c["items"]}
            for comp in p["components"]:
                it = menus[p["vendor_id"]][comp["item_oid"]]
                assert "peanut" not in it["allergens"] and ({"halal", "vegan"} & set(it["diets"])), it["name"]
        return f"picks now {titles}"

    def log_meal():
        vendors = run.get("/vendors")
        v = next(v for v in vendors if v["name"] == "Sazon")
        menu = run.get(f"/vendors/{v['id']}/menu")
        item = next(i for c in menu["courses"] if c["name"] == "Choose Protein" for i in c["items"]
                    if i["name"] == "Chipotle Chicken")
        p = next(p for p in item["portions"] if p["is_default"])
        r = requests.post(f"{base}/orders/manual", headers=run.h, timeout=30, json={
            "user_id": state["devil"], "vendor_id": v["id"],
            "items": [{"item_oid": item["item_oid"], "uofm_oid": p["uofm_oid"], "price": 12.85}]})
        r.raise_for_status()
        t = run.get("/today", user_id=state["devil"])
        assert len(t["meals"]) == state["devil_meals"] + 1, "logged meal not on Today"
        return f"logged {item['name']} ({r.json()['macros']['protein_g']:.0f} g); Today shows {len(t['meals'])} meals"

    run.step("reset demo (hold back newest receipt)", do_reset)
    run.step("William forwards a receipt (Postmark)", forward)
    run.step("William: Today coach card", william_today)
    run.step("switch to Blue Devil: Today", devil_today)
    run.step("Eat next (Balanced)", eat_next("balanced"))
    run.step("Eat next (More protein)", eat_next("protein"))
    run.step("toggle Halal + Peanut -> picks change, none violate", restrictions)
    run.step("log an in-person meal -> shows on Today", log_meal)
    return run


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("API_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args()
    clean = 0
    for i in range(a.runs):
        print(f"Run {i + 1}:")
        t = time.perf_counter()
        run = rehearse(a.base.rstrip("/"), os.environ["APP_TOKEN"])
        total = time.perf_counter() - t
        print(f"  => {'CLEAN' if run.ok else 'FAILED'} in {total:.1f} s\n")
        clean += run.ok
    print(f"{clean}/{a.runs} clean runs")
    sys.exit(0 if clean == a.runs else 1)


if __name__ == "__main__":
    main()
