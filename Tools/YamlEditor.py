from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import shutil
import subprocess
import tempfile
import sys
import re

import yaml


# ------------------------------------------------------------
# Datenklassen
# ------------------------------------------------------------
# Erlaubte Werte der Rezept-/Zutatenfelder (docs/ProposeLogic.md V). Die Auswahllisten in
# creation.html / ingredients.html muessen dazu passen.
ORIGINS = ("asian", "oriental", "mexican", "indian", "italian", "home-style", "mediterranean", "american")
COOKING_METHODS = ("oven", "pan", "pot", "grill", "raw", "steam")
RECIPE_SPECS = ("soup", "salad", "casserole", "bowl", "sandwich", "others")
NOT_SPECIFIC = "not specific"     # main_ingredient ohne bestimmte Hauptzutat
ALLERGENS = ("lactose", "gluten")  # Zutat hat <allergen>_free: true / false / null (= unbekannt)


@dataclass(frozen=True)
class Ingredient:
    ingredient_id: int
    name: str
    veg_type: Optional[str]
    spice: Optional[bool]
    lactose_free: Optional[bool] = None   # None = unbekannt
    gluten_free: Optional[bool] = None



@dataclass(frozen=True)
class Recipe:
    recipe_id: int
    name: str
    veg_type: str
    cook_minutes: Optional[int]
    prep_minutes: Optional[int]
    sweet: Optional[bool]         # Flag (süß ja/nein), NICHT die Kategorie
    instructions: Optional[str]
    variant_of: Optional[int]
    recipe_type: str    # main_dish, sweet, dip, wuerzung, side_dish, snack
    origin: Tuple[str, ...] = ()            # ORIGINS, mehrere moeglich
    cooking_method: Optional[str] = None    # COOKING_METHODS
    recipe_spec: Optional[str] = None       # RECIPE_SPECS
    main_ingredient: Optional[int | str] = None   # ingredient_id oder NOT_SPECIFIC


def data_problems(data: dict) -> list[str]:
    """Prueft die neuen Rezept-/Zutatenfelder auf erlaubte Werte. Fehlende Felder sind ok
    (= noch nicht gepflegt). Rueckgabe: Liste lesbarer Fehler, leer = alles gut."""
    problems = []
    ingredient_ids = {i.get("ingredient_id") for i in data.get("ingredients", [])}
    links = {(ri.get("recipe_id"), ri.get("ingredient_id")) for ri in data.get("recipe_ingredients", [])}

    for i in data.get("ingredients", []):
        for a in ALLERGENS:
            if i.get(f"{a}_free") not in (None, True, False):
                problems.append(f"ingredient {i.get('ingredient_id')}: {a}_free must be true/false/null")

    for r in data.get("recipes", []):
        rid = r.get("recipe_id")
        origin = r.get("origin") or []
        for o in origin if isinstance(origin, list) else [origin]:
            if o not in ORIGINS:
                problems.append(f"recipe {rid}: unknown origin {o!r}")
        if r.get("cooking_method") not in (None, *COOKING_METHODS):
            problems.append(f"recipe {rid}: unknown cooking_method {r.get('cooking_method')!r}")
        if r.get("recipe_spec") not in (None, *RECIPE_SPECS):
            problems.append(f"recipe {rid}: unknown recipe_spec {r.get('recipe_spec')!r}")
        if (r.get("prep_minutes") is None) != (r.get("cook_minutes") is None):
            problems.append(f"recipe {rid}: only one of prep_minutes / cook_minutes is set")
        main = r.get("main_ingredient")
        if main not in (None, NOT_SPECIFIC):
            if main not in ingredient_ids:
                problems.append(f"recipe {rid}: main_ingredient {main!r} is not an ingredient_id")
            elif (rid, main) not in links:
                problems.append(f"recipe {rid}: main_ingredient {main} is not in its ingredient list")
    return problems


@dataclass(frozen=True)
class RecipeIngredientLink:
    recipe_id: int
    ingredient_id: int
    quantity: Optional[float]
    unit: Optional[str]
    note: Optional[str]

def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Fehlende Datei: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

def save_yaml(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def update_yaml(path, key,val):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump({ key: val if isinstance(val, list) else [] }, f, sort_keys=False, allow_unicode=True)

def next_id(doc: dict, collection_key: str, id_key: str) -> int:
    """Return the next numeric id for a list inside a YAML document."""
    max_id = 0
    for row in doc.get(collection_key, []):
        current_id = int(row.get(id_key, 0) or 0)
        if current_id > max_id:
            max_id = current_id
    return max_id + 1


def next_ingredient_id(doc: dict) -> int:
    """Return the next ingredient_id from an ingredients YAML document."""
    return next_id(doc, "ingredients", "ingredient_id")


def parse_bool(s: str) -> bool:
    """Parse common command-line boolean strings."""
    value = s.strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("Expected boolean (true/false)")