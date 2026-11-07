"""Pydantic models shared by routes (SPEC 6, 9)."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Targets(BaseModel):
    calories: int = Field(ge=1800)
    protein_g: int


class Settings(BaseModel):
    semester_end: date
    targets: Targets
    goal: Literal["balanced", "build_muscle", "budget"] = "balanced"
    require_diets: list[Literal["halal", "vegan", "vegetarian"]] = []
    avoid_allergens: list[Literal["egg", "fish", "gluten", "milk", "peanut", "sesame",
                                  "shellfish", "soy", "tree_nut", "wheat"]] = []
    show_calories: bool = True


class User(BaseModel):
    id: int
    name: str
    is_demo: bool


class ParsedItem(BaseModel):
    name: str
    price: float                     # effective price (item price, else sum of component prices)
    components: list[str] = []
    priced_component: str | None = None


class ParsedReceipt(BaseModel):
    order_number: str
    placed_at: datetime              # UTC
    vendor_raw: str
    building: str
    items: list[ParsedItem]
    subtotal: float
    tax: float
    total: float
    points_spent: float              # "Student Food" tender
    swipes_used: int
    swipe_value: float
