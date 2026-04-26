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
@dataclass(frozen=True)
class Ingredient:
    ingredient_id: int
    name: str
    veg_type: Optional[str]
    spice: Optional[bool]



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