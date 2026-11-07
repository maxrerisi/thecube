from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_token
from app.core import clock, hours, menu
from app.db import get_conn

router = APIRouter(dependencies=[Depends(require_token)])


def vendor_row(conn, vendor_id: int) -> dict:
    v = conn.execute("""SELECT v.id, v.name, v.building, v.unit_oid, v.hours, u.kind FROM vendors v
                        LEFT JOIN nn_units u USING (unit_oid) WHERE v.id = %s""", (vendor_id,)).fetchone()
    if not v:
        raise HTTPException(404, f"no vendor {vendor_id}")
    return v


@router.get("/vendors")
def list_vendors(conn=Depends(get_conn)):
    at = clock.now()
    rows = conn.execute("""SELECT v.id, v.name, v.building, v.unit_oid, v.hours, u.kind FROM vendors v
                           LEFT JOIN nn_units u USING (unit_oid) ORDER BY v.name""").fetchall()
    return [{"id": v["id"], "name": v["name"], "building": v["building"], "unit_oid": v["unit_oid"],
             "has_nutrition": v["unit_oid"] is not None, "open_now": hours.is_open(v["hours"], at),
             "hours": v["hours"]} for v in rows]


@router.get("/vendors/{vendor_id}/menu")
def vendor_menu(vendor_id: int, conn=Depends(get_conn)):
    v = vendor_row(conn, vendor_id)
    if v["unit_oid"] is None:
        return {"vendor": {"id": v["id"], "name": v["name"]}, "has_nutrition": False, "menu_date": None, "courses": []}
    items = menu.current_items(conn, v["unit_oid"])
    by_oid, by_name = menu.known_prices(conn, vendor_id)
    courses: dict[str, list] = {}
    for i in items:
        courses.setdefault(i["course"] or "Other", []).append({
            "item_oid": i["item_oid"], "name": i["name"], "allergens": i["allergens"], "diets": i["diets"],
            "ingredients": i["ingredients"], "meal": i["meal"], "known_price": menu.price_for(i, by_oid, by_name),
            "portions": [{"uofm_oid": p["uofm_oid"], "name": p["portion_name"], "is_default": p["is_default"],
                          **{k: p[k] for k in ("grams", "calories", "protein_g", "carbs_g", "fat_g",
                                               "fiber_g", "sugar_g", "sodium_mg")}} for p in i["portions"]],
        })
    return {"vendor": {"id": v["id"], "name": v["name"]}, "has_nutrition": True,
            "menu_date": items[0]["menu_date"].isoformat() if items and items[0]["menu_date"] else None,
            "courses": [{"name": c, "items": its} for c, its in courses.items()]}
