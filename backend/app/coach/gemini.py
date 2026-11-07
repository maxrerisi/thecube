"""Coach (SPEC 11): Gemini writes words; code checks every number and falls back to templates.

recap(payload)  -> {headline, message, tone, source}
pick(result)    -> {chosen_index, headline, reason, source}

Flow: build input (numbers computed by code) -> cache by input hash -> Gemini (JSON schema)
-> validate (schema, lengths, every number in the output appears in the input, no calorie
talk when show_calories is false) -> one retry -> template fallback. source = "gemini" |
"cache" | "template". Never raises: no key / network error / bad output -> template.
"""
import hashlib
import json
import logging
import os
import re

from app.coach import prompts

log = logging.getLogger("coach")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
CAL_WORDS = re.compile(r"\b(cal|cals|calorie|calories|kcal|energy)\b", re.I)
_client = None


def _gemini():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            return None
        from google import genai
        _client = genai.Client(api_key=key)
    return _client


def _call_gemini(kind: str, data: dict) -> dict | None:
    client = _gemini()
    if client is None:
        return None
    from google.genai import types
    instr = prompts.RECAP_INSTRUCTIONS if kind == "recap" else prompts.PICK_INSTRUCTIONS
    schema = prompts.RECAP_SCHEMA if kind == "recap" else prompts.PICK_SCHEMA
    resp = client.models.generate_content(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        contents=f"{instr}\n\nInput JSON:\n{json.dumps(data, sort_keys=True)}",
        config=types.GenerateContentConfig(system_instruction=prompts.SYSTEM, response_mime_type="application/json",
                                           response_json_schema=schema))  # no temperature (SPEC 3)
    return json.loads(resp.text)


# ---------- validation ----------

def input_numbers(data) -> set[str]:
    """Every number in the input, as the strings a writer could use: 74.0 -> {"74.0", "74"}."""
    out: set[str] = set()
    def add(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            f = float(x)
            out.update({repr(f), f"{f:g}", f"{f:.2f}", f"{f:.1f}"})
            if f == int(f):
                out.add(str(int(f)))
        elif isinstance(x, str):
            for n in NUM.findall(x):
                out.add(n.replace(",", ""))
                add(float(n.replace(",", "")))
        elif isinstance(x, dict):
            for v in x.values():
                add(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                add(v)
    add(data)
    return out


def check(kind: str, out: dict, data: dict) -> list[str]:
    errs = []
    if not isinstance(out, dict):
        return ["not an object"]
    text_keys = ("headline", "message") if kind == "recap" else ("headline", "reason")
    for k in text_keys:
        if not isinstance(out.get(k), str) or not out[k].strip():
            errs.append(f"missing {k}")
    if errs:
        return errs
    if len(out["headline"]) > 60:
        errs.append("headline > 60 chars")
    if len(out[text_keys[1]]) > 280:
        errs.append(f"{text_keys[1]} > 280 chars")
    if kind == "recap" and out.get("tone") not in ("praise", "nudge", "warning"):
        errs.append("bad tone")
    if kind == "pick" and out.get("chosen_index") not in range(len(data.get("picks", []))):
        errs.append("bad chosen_index")
    allowed = input_numbers(data)
    for k in text_keys:
        for n in NUM.findall(out[k]):
            n = n.replace(",", "").rstrip(".")
            if n not in allowed and f"{float(n):g}" not in allowed:
                errs.append(f"number {n} not in input")
        if data.get("show_calories") is False and CAL_WORDS.search(out[k]):
            errs.append("calorie talk with show_calories off")
    return errs


# ---------- templates (fallback) ----------

def _recap_template(d: dict) -> dict:
    p, tgt, pts = d["protein_g"], d["protein_target_g"], d.get("points") or {}
    left = round(max(tgt - p, 0))
    if pts.get("runs_out_on") and not pts.get("on_pace", True):
        tone = "warning"
        headline = f"Points run out {pts['runs_out_on']}"
        msg = (f"At {pts['trailing_daily']} a day you'll run out before the semester ends; "
               f"{pts['daily_budget']} a day lasts. {round(p)} g of {tgt} g protein so far today.")
    elif p >= tgt:
        tone, headline = "praise", f"Protein target hit: {round(p)} g"
        msg = f"You've reached {round(p)} g of {tgt} g protein today. Keep the next meal balanced."
    else:
        tone, headline = "nudge", f"{round(p)} g protein so far, {left} g to go"
        msg = f"{left} g of protein to go today. You hit your target on {d['protein_hit_days_7']} of the last 7 days."
    return {"headline": headline[:60], "message": msg[:280], "tone": tone}


def _pick_template(d: dict) -> dict:
    best = d["picks"][0]
    reason = f"{best['protein_g']} g protein for {best['points_cost']} points"
    if d.get("headroom") is not None:
        reason += f", with {d['headroom']} points of headroom today"
    return {"chosen_index": 0, "headline": f"{best['title']} at {best['vendor']}"[:60], "reason": reason + "."}


# ---------- entry points ----------

def _run(kind: str, data: dict, conn=None, call=None) -> dict:
    call = call or _call_gemini
    h = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
    if conn is not None:
        row = conn.execute("SELECT output FROM coach_cache WHERE kind = %s AND input_hash = %s", (kind, h)).fetchone()
        if row:
            return {**row["output"], "source": "cache"}
    for attempt in range(2):
        try:
            out = call(kind, data)
        except Exception as e:  # network, quota, bad JSON
            log.warning("coach %s attempt %d failed: %s", kind, attempt, e)
            out = None
        if out is None and attempt == 0 and call is _call_gemini and _gemini() is None:
            break  # no key: don't retry
        errs = check(kind, out, data) if out is not None else ["no output"]
        if not errs:
            if conn is not None:
                conn.execute("""INSERT INTO coach_cache (kind, input_hash, output) VALUES (%s, %s, %s)
                                ON CONFLICT DO NOTHING""", (kind, h, json.dumps(out)))
            return {**out, "source": "gemini"}
        log.info("coach %s attempt %d rejected: %s", kind, attempt, errs)
    out = _recap_template(data) if kind == "recap" else _pick_template(data)
    return {**out, "source": "template"}


def _words(iso: str | None) -> str | None:
    """'2026-12-12' -> 'December 12' (computed here so the model never formats dates)."""
    if not iso:
        return None
    from datetime import date
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}"


def _days_between(a: str | None, b: str | None) -> int | None:
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days if a and b else None


def recap_input(today: dict) -> dict:
    """Only what the card needs, numbers already computed by code (SPEC 11)."""
    pts = today["points"]
    d = {
        "show_calories": today["show_calories"],
        "protein_g": today["eaten"]["protein_g"], "protein_target_g": today["targets"]["protein_g"],
        "protein_left_g": round(max(today["targets"]["protein_g"] - today["eaten"]["protein_g"], 0)),
        "protein_hit_days_7": today["protein_hit_days_7"], "meals_today": len(today["meals"]),
        "points": None if pts["points"] is None else {
            "points_left": pts["points"], "swipes_left": pts["swipes"], "days_left": pts["days_left"],
            "daily_budget": pts["daily_budget"], "spent_today": pts["spent_today"],
            "trailing_daily": pts["trailing_daily"], "on_pace": pts["on_pace"],
            "runs_out_on": _words(pts["runout"]), "semester_ends_on": _words(today.get("semester_end")),
            "days_early": _days_between(pts["runout"], today.get("semester_end"))},
    }
    if today["show_calories"]:
        d["calories"], d["calorie_target"] = today["eaten"]["calories"], today["targets"]["calories"]
    return d


def _headroom_facts(cost: float, headroom: float | None) -> dict:
    if headroom is None:
        return {}
    over = round(cost - headroom, 2)
    return {"fits_headroom": over <= 0, **({"over_headroom_by": over} if over > 0 else {})}


def pick_input(result: dict, show_calories: bool) -> dict:
    words = []
    r = result["restrictions"]
    if r["require_diets"]:
        words.append("must be " + " and ".join(r["require_diets"]))
    if r["avoid_allergens"]:
        words.append("avoids " + ", ".join(a.replace("_", " ") for a in r["avoid_allergens"]))
    return {
        "show_calories": show_calories, "bias": result["bias"], "headroom": result["headroom"],
        "protein_needed_this_meal_g": result["per_meal_target"]["protein_g"],
        "restrictions": "; ".join(words) or "none",
        "picks": [{"index": i, "vendor": p["vendor"], "title": p["title"], "protein_g": p["protein_g"],
                   "points_cost": p["points_cost"],
                   "meets_protein_needed": p["protein_g"] >= result["per_meal_target"]["protein_g"],
                   **_headroom_facts(p["points_cost"], result["headroom"]),
                   **({"calories": p["calories"]} if show_calories else {})}
                  for i, p in enumerate(result["picks"])],
    }


def recap(today: dict, conn=None, call=None) -> dict:
    return _run("recap", recap_input(today), conn, call)


def pick(result: dict, show_calories: bool, conn=None, call=None) -> dict | None:
    if not result["picks"]:
        return None
    return _run("pick", pick_input(result, show_calories), conn, call)
