"""Deterministic parser for Duke Transact Mobile Ordering receipt emails (.eml).

Usage: python3 spikes/parse_receipt.py emails/ > spikes/receipts.json
"""
import email, html, json, re, sys
from email import policy
from pathlib import Path

MONEY = re.compile(r"-?\$(\d+(?:,\d{3})*\.\d{2})")

def money(s):
    m = MONEY.search(s or "")
    return float(m.group(1).replace(",", "")) if m else None

def rows(html_body):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html_body, flags=re.S | re.I):
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", tr, flags=re.S | re.I)
        parsed = []
        for attrs, inner in cells:
            raw = html.unescape(re.sub(r"<[^>]+>", "", inner)).replace("\xa0", " ")
            parsed.append({"text": raw.strip(), "indented": raw.startswith("    "),
                           "bold": "<b>" in inner.lower(), "center": "center" in attrs})
        if parsed and any(c["text"] for c in parsed):
            out.append(parsed)
    return out

def parse(path):
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=policy.default)
    part = msg.get_body(("html", "plain"))
    body = part.get_content()
    r = rows(body)
    header = [row[0]["text"] for row in r if len(row) == 1 or row[0]["center"]]
    rec = {"file": Path(path).name, "from": str(msg["From"]), "subject": str(msg["Subject"]),
           "order_number": header[0].lstrip("#"), "placed_at_local": header[1],
           "target_time": header[2].replace("Target:", "").strip(),
           "vendor": header[3], "building": header[4], "address": header[5],
           "items": [], "subtotal": None, "tax": None, "total": None,
           "tenders": [], "notes": []}
    section = "items"
    for row in r:
        if row[0]["center"]:
            continue
        label = row[0]["text"]; amt = money(row[1]["text"]) if len(row) > 1 else None
        if label in ("Subtotal", "Tax", "Total"):
            rec[label.lower()] = amt; section = "totals" if label != "Total" else "tenders"; continue
        if label == "Transaction #":
            section = "done"; continue
        if section == "items":
            m = re.match(r"(\d+)\.\s*(.+)", label)
            if m and not row[0]["indented"]:
                rec["items"].append({"qty_index": int(m.group(1)), "name": m.group(2).strip(),
                                     "price": amt, "components": []})
            elif rec["items"] and label:
                rec["items"][-1]["components"].append({"name": label, "price": amt})
        elif section == "tenders":
            if label == "DukeCard":
                continue
            right = row[1]["text"] if len(row) > 1 else ""
            if label.startswith("Board Plan"):
                rec["tenders"].append({"account": "board_plan_swipe",
                                       "amount": money(right) or money(label),
                                       "detail": f"{label} | {right}"})
            elif amt is not None:
                rec["tenders"].append({"account": label, "amount": amt})
            else:
                rec["notes"].append(label)
    for it in rec["items"]:  # price may sit on a component (e.g. the protein)
        it["effective_price"] = it["price"] if it["price"] is not None else sum(
            c["price"] or 0 for c in it["components"])
    s = sum(i["effective_price"] for i in rec["items"])
    rec["check_items_sum_eq_subtotal"] = abs(s - (rec["subtotal"] or 0)) < 0.01
    rec["check_tenders_sum_eq_total"] = abs(sum(t["amount"] or 0 for t in rec["tenders"]) - (rec["total"] or 0)) < 0.01
    return rec

if __name__ == "__main__":
    d = Path(sys.argv[1] if len(sys.argv) > 1 else "emails")
    out = []
    for p in sorted(d.glob("*.eml")):
        try:
            out.append(parse(p))
        except Exception as e:
            out.append({"file": p.name, "error": repr(e)})
    json.dump(out, sys.stdout, indent=2)
