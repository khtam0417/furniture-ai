"""Apartment configurations. An apartment type says which rooms exist, never how big they are.

Each furnished room (bedroom, living area, or the single studio room) is an ordinary per-room project with its
own photos, evidence, preferences, budget, plans and history. Bathrooms and the kitchen are fixed functional
spaces: listed in the overview, never furnished, never given evidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

PRESETS = {
    "studio": (0, 1),
    "1b1b": (1, 1),
    "2b1b": (2, 1),
    "2b2b": (2, 2),
    "3b2b": (3, 2),
}
MAX_BEDROOMS = 5
MAX_BATHROOMS = 4


class SelectedBuilding(BaseModel):
    """The building the user chose from the candidates (identity only; never room geometry or a unit)."""

    key: str = Field(max_length=80)
    kind: Literal["checked", "web", "url"]
    name: str = Field(default="", max_length=160)
    address: str | None = Field(default=None, max_length=160)  # None = unknown (never guessed)
    site: str = Field(default="", max_length=255)
    url: str = Field(default="", max_length=2048)
    directory: str | None = Field(default=None, max_length=80)
    selected_at: str = Field(default="", max_length=40)


class ApartmentContext(BaseModel):
    """Shared apartment context (not room geometry). `unit_label` is private: never sent to search or fetches."""

    property_name: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=40)
    zip: str = Field(default="", max_length=10, pattern=r"^$|^\d{5}(?:-\d{4})?$")
    unit_label: str = Field(default="", max_length=40)
    property_url: str = Field(default="", max_length=2048)
    condition: Literal["new", "secondhand", "either"] = "either"
    fulfillment: Literal["local_pickup", "delivery", "either"] = "either"
    timing: str = Field(default="", max_length=60)
    building: SelectedBuilding | None = None  # set by "This is my building"; older versions simply lack it

    def public_location(self) -> str:
        """City/state/ZIP only — never the unit label."""
        return " ".join(x for x in (self.city.strip(), self.state.strip(), self.zip.strip()) if x)


class CreateApartment(BaseModel):
    name: str = Field(default="My apartment", min_length=1, max_length=80)
    preset: Literal["studio", "1b1b", "2b1b", "2b2b", "3b2b", "custom"]
    bedrooms: int | None = Field(default=None, ge=0, le=MAX_BEDROOMS)
    bathrooms: int | None = Field(default=None, ge=1, le=MAX_BATHROOMS)
    context: ApartmentContext | None = None

    @model_validator(mode="after")
    def _counts(self):
        if self.preset == "custom":
            if self.bedrooms is None or self.bathrooms is None:
                raise ValueError("Custom apartments need bedroom and bathroom counts.")
        else:
            b, ba = PRESETS[self.preset]
            if (self.bedrooms is not None and self.bedrooms != b) or (self.bathrooms is not None and self.bathrooms != ba):
                raise ValueError("Counts do not match the chosen apartment type; use 'custom'.")
            self.bedrooms, self.bathrooms = b, ba
        return self


def label_for(bedrooms: int, bathrooms: int) -> str:
    if bedrooms == 0:
        return f"Studio · {bathrooms} bath" + ("s" if bathrooms > 1 else "")
    return f"{bedrooms} bed · {bathrooms} bath"


def rooms_for(name: str, bedrooms: int) -> list[tuple[str, str, str]]:
    """(project name, room_type, label) for each furnished room."""
    if bedrooms == 0:
        return [(f"{name} — Studio", "studio", "Studio")]
    rooms = [(f"{name} — Bedroom {i}", "bedroom", f"Bedroom {i}") for i in range(1, bedrooms + 1)]
    rooms.append((f"{name} — Living area", "living_room", "Living area"))
    return rooms


def fixed_spaces(bedrooms: int, bathrooms: int) -> list[dict]:
    spaces = [{"kind": "bathroom", "label": f"Bath {i}" if bathrooms > 1 else "Bath"} for i in range(1, bathrooms + 1)]
    spaces.append({"kind": "kitchen", "label": "Kitchen" if bedrooms else "Kitchen (inside the studio)"})
    return spaces
