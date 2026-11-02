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
COOKING_METHODS = ("oven", "pan", "pot", "grill", "raw", "steam", "microwave")
RECIPE_SPECS = ("soup", "stew", "salad", "pasta", "pan_dish", "casserole", "bowl", "sandwich", "baked", "sauce",
                "others")   # gleiche Reihenfolge wie generate_cookbook_PDF.SPEC_ORDER
NOT_SPECIFIC = "not specific"     # main_ingredient ohne bestimmte Hauptzutat
# Saison zweistufig: "summer" = Empfehlung (Bonus in der Saison, sonst normal vorschlagbar),
# "only_summer" = nur in der Saison vorschlagen (harter Filter). all / always / fehlt = ganzjaehrig.
SEASONS = ("spring", "summer", "autumn", "winter")
SEASON_VALUES = ("all", "always", *SEASONS, *(f"only_{s}" for s in SEASONS))
ALLERGENS = ("lactose", "gluten")  # Zutat hat <allergen>_free: true / false / null (= unbekannt)
# Fleischsorte einer Fleisch-Zutat (null = zaehlt nicht als Fleischsorte, z.B. Bruehe). Das Rezept
# speichert daraus meat_types - beim Bearbeiten aus den Zutaten befuellt, beim Daempfen vom Rezept gelesen.
MEAT_TYPES = ("beef", "pork", "poultry", "lamb", "game", "fish", "other")   # fish zaehlt wie eine Fleischsorte
# Pro User eine Datei server_data/user_data/user_<id>.yaml mit seiner history und seinen Default-Bewertungen
# (default_ratings: 0-10, null = keine - gilt, solange die history fuer diesen Wert noch keine Bewertung hat;
# gepflegt auf der Entwicklerseite /dev). Die Logik sieht davon nur data["history"] / data["default_ratings"].
USER_KEYS = ("history", "default_ratings")
DEFAULT_RATING_KEYS = ("taste_rating", "effort_rating", "repeat_rating")
DEFAULT_RATING_SCALE = (0, 10)
USER_FILE_HEADER = """# Daten EINES Users (Dateiname = user_id aus users.yaml), vom Server geschrieben.
# history:         pro Rezept ein Eintrag - Kochdaten, Bewertungen, Zeiten (siehe RatingLogic)
# default_ratings: Default-Bewertung fuer Gerichte, die man kennt, aber noch nicht ueber die App gekocht hat
#                  (taste / effort / repeat 0-10, Entwicklerseite /dev). name nur zur Orientierung.
"""
# Zutat (normal) | Grundzutat (Wasser, Mehl, Zucker, Staerke ...) | Gewuerz (Sojasauce, Pfeffer, Salz ...)
INGREDIENT_CATEGORIES = ("ingredient", "basic", "spice")
NUTRITION_KEYS = ("kcal", "protein", "carbs", "fat")   # jeweils pro `unit` DER ZUTAT (nicht pro Rezept-Einheit)

# Einheitliches Format jeder Zutat in ingredients.yaml: Reihenfolge der Felder + Standardwert.
INGREDIENT_FIELDS = {
    "ingredient_id": None,
    "name": None,
    "unit": None,             # Bezugseinheit der Naehrwerte, zugleich Standard-Einheit im Rezept
    "veg_type": None,         # vegan | vegetarian | fish | meat
    "meat_type": None,        # MEAT_TYPES oder null
    "category": "ingredient", # INGREDIENT_CATEGORIES
    "side_dish": False,
    "lactose_free": None,     # true / false / null (= unbekannt)
    "gluten_free": None,
    "shelf_life_days": None,
    "kcal": None,
    "protein": None,          # g
    "carbs": None,            # g
    "fat": None,              # g
}


def normalize_ingredient(ing: dict) -> dict:
    """Bringt eine Zutat ins einheitliche Format (INGREDIENT_FIELDS): fehlende Felder mit Standardwert,
    feste Reihenfolge, unbekannte Felder bleiben hinten erhalten. Altes `spice: true` -> category spice."""
    ing = dict(ing)
    if ing.pop("spice", None) and not ing.get("category"):
        ing["category"] = "spice"
    out = {key: ing.pop(key, default) for key, default in INGREDIENT_FIELDS.items()}
    out["category"] = out["category"] or "ingredient"
    out.update(ing)
    return out


@dataclass(frozen=True)
class Ingredient:
    ingredient_id: int
    name: str
    veg_type: Optional[str]
    category: str = "ingredient"          # INGREDIENT_CATEGORIES
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
    main_ingredient: Tuple[int, ...] = ()   # ingredient_ids der Hauptzutaten, () = keine (main_ingredients())
    season: Optional[str] = None            # SEASON_VALUES (fehlt = all)
    side_dish: Optional[int] = None         # ingredient_id der Beilage oder None (= keine Beilage)
    meat_types: Tuple[str, ...] = ()        # MEAT_TYPES


def season_parts(value) -> tuple[Optional[str], bool]:
    """Saisonfeld -> (Saison oder None = ganzjaehrig, nur in der Saison?). "only_summer" -> ("summer", True)."""
    value = value or "all"
    only = value.startswith("only_")
    season = value[len("only_"):] if only else value
    return (season if season in SEASONS else None), only


def main_ingredients(value) -> list:
    """main_ingredient eines Rezepts als Liste: eine ID, eine Liste von IDs oder None / "not specific"
    (= keine Hauptzutat -> [])."""
    if value is None or value == NOT_SPECIFIC:
        return []
    return [v for v in value if v is not None] if isinstance(value, list) else [value]


def default_rating(data: dict, recipe_id) -> dict:
    """Default-Bewertung eines Rezepts aus default_ratings.yaml: {taste_rating, effort_rating, repeat_rating},
    nicht gesetzte Werte = None."""
    entry = next((d for d in data.get("default_ratings", []) if d.get("recipe_id") == recipe_id), {})
    return {k: entry.get(k) for k in DEFAULT_RATING_KEYS}


def meat_types_of(data: dict, ingredient_ids) -> list[str]:
    """Fleischsorten der Zutaten (meat_type, ohne null), sortiert - Vorschlag fuer das Rezeptfeld meat_types."""
    by_id = {i.get("ingredient_id"): i for i in data.get("ingredients", [])}
    return sorted({by_id[i]["meat_type"] for i in ingredient_ids if by_id.get(i, {}).get("meat_type")})


# ------------------------------------------------------------
# Vorschlaege beim Erstellen (nur Vorschlag - der User muss bestaetigen)
# ------------------------------------------------------------
# grobe Gramm pro Einheit, nur um beim Vorschlag die schwerste Zutat zu finden
UNIT_GRAMS = {"g": 1, "kg": 1000, "ml": 1, "l": 1000, "liter": 1000, "el": 15, "tl": 5, "tasse": 150,
              "stück": 100, "stueck": 100, "prise": 0.5, "bund": 50, "scheibe": 20, "packung": 250,
              "dose": 400, "becher": 200, "zehe": 5, "": 100}


def _norm(text) -> str:
    text = str(text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return text


def approx_grams(quantity, unit) -> float:
    return float(quantity or 0) * UNIT_GRAMS.get(_norm(unit).strip(), 100)


def _choice(ing: dict, reason: str) -> dict:
    return {"ingredient_id": ing.get("ingredient_id"), "name": ing.get("name"), "reason": reason}


def suggest_main_and_side(data: dict, name: str, items: list[dict]) -> dict:
    """Vorschlag fuer Hauptzutat und Beilage eines Rezepts aus Name + Zutatenliste.
    items: [{ingredient_id, quantity, unit}]. Rueckgabe {"main_ingredient": {...} | None, "side_dish": ...,
    "meat_types": [...]}.
    - Beilage: Zutat mit side_dish: true (bei mehreren die schwerste)
    - Hauptzutat: normale Zutat (keine Beilage / Grundzutat / Gewuerz), deren Name im Rezeptnamen
      vorkommt (oder umgekehrt), sonst die mit dem groessten Gewichtsanteil."""
    by_id = {i.get("ingredient_id"): normalize_ingredient(i) for i in data.get("ingredients", [])}
    parts = [(by_id[it.get("ingredient_id")], approx_grams(it.get("quantity"), it.get("unit")))
             for it in items if it.get("ingredient_id") in by_id]
    heaviest = lambda cands: max(cands, key=lambda p: p[1]) if cands else None

    sides = [p for p in parts if p[0]["side_dish"]]
    side = heaviest(sides)
    mains = [p for p in parts if not p[0]["side_dish"] and p[0]["category"] == "ingredient"]
    recipe_name = _norm(name)
    tokens = [t for t in re.split(r"[^a-z]+", recipe_name) if len(t) >= 4]
    by_name = [p for p in mains if (len(_norm(p[0]["name"])) >= 3 and _norm(p[0]["name"]) in recipe_name)
               or any(t in _norm(p[0]["name"]) for t in tokens)]
    if by_name:
        main = _choice(heaviest(by_name)[0], "steht im Rezeptnamen")
    elif mains:
        ing, grams = heaviest(mains)
        main = _choice(ing, f"größter Gewichtsanteil (~{grams:.0f} g)")
    else:
        main = None
    return {"main_ingredient": main,
            "side_dish": _choice(side[0], "Beilagen-Zutat") if side else None,
            "meat_types": meat_types_of(data, [it.get("ingredient_id") for it in items])}


def side_dish_variant_of(data: dict, recipe_id, items: list[dict]) -> Optional[dict]:
    """Gibt es schon ein Rezept mit denselben (normalen) Zutaten, aber einer anderen Beilage?
    Dann ist das neue Rezept vermutlich eine Variante davon (z.B. einmal mit Nudeln, einmal mit Reis).
    Rueckgabe {"recipe_id", "name"} des Hauptrezepts der Familie oder None."""
    by_id = {i.get("ingredient_id"): normalize_ingredient(i) for i in data.get("ingredients", [])}
    core = lambda ids: {i for i in ids if i in by_id and not by_id[i]["side_dish"] and by_id[i]["category"] == "ingredient"}
    sides = lambda ids: {i for i in ids if i in by_id and by_id[i]["side_dish"]}
    mine = {it.get("ingredient_id") for it in items}
    if not core(mine) or not sides(mine):
        return None
    links = defaultdict(set)
    for ri in data.get("recipe_ingredients", []):
        links[ri.get("recipe_id")].add(ri.get("ingredient_id"))
    recipes = {r.get("recipe_id"): r for r in data.get("recipes", [])}
    root_of = lambda r: r.get("variant_of") or r.get("recipe_id")
    own_root = root_of(recipes[recipe_id]) if recipe_id in recipes else recipe_id
    for r in recipes.values():
        root = root_of(r)
        if own_root is not None and own_root in (r.get("recipe_id"), root):   # eigene Familie
            continue
        other = links[r.get("recipe_id")]
        if core(other) == core(mine) and sides(other) and sides(other) != sides(mine):
            return {"recipe_id": root, "name": recipes.get(root, r).get("name")}
    return None


def data_problems(data: dict) -> list[str]:
    """Prueft die neuen Rezept-/Zutatenfelder auf erlaubte Werte. Fehlende Felder sind ok
    (= noch nicht gepflegt). Rueckgabe: Liste lesbarer Fehler, leer = alles gut."""
    problems = []
    ingredient_ids = {i.get("ingredient_id") for i in data.get("ingredients", [])}
    links = {(ri.get("recipe_id"), ri.get("ingredient_id")) for ri in data.get("recipe_ingredients", [])}

    for i in data.get("ingredients", []):
        iid = i.get("ingredient_id")
        for a in ALLERGENS:
            if i.get(f"{a}_free") not in (None, True, False):
                problems.append(f"ingredient {iid}: {a}_free must be true/false/null")
        if i.get("category") not in (None, *INGREDIENT_CATEGORIES):
            problems.append(f"ingredient {iid}: unknown category {i.get('category')!r}")
        if i.get("meat_type") not in (None, *MEAT_TYPES):
            problems.append(f"ingredient {iid}: unknown meat_type {i.get('meat_type')!r}")
        for key in NUTRITION_KEYS:
            value = i.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                problems.append(f"ingredient {iid}: {key} must be a number >= 0 or null")

    for r in data.get("recipes", []):
        rid = r.get("recipe_id")
        origin = r.get("origin") or []
        for o in origin if isinstance(origin, list) else [origin]:
            if o not in ORIGINS:
                problems.append(f"recipe {rid}: unknown origin {o!r}")
        if r.get("cooking_method") not in (None, *COOKING_METHODS):
            problems.append(f"recipe {rid}: unknown cooking_method {r.get('cooking_method')!r}")
        if r.get("season") not in (None, *SEASON_VALUES):
            problems.append(f"recipe {rid}: unknown season {r.get('season')!r}")
        if r.get("recipe_spec") not in (None, *RECIPE_SPECS):
            problems.append(f"recipe {rid}: unknown recipe_spec {r.get('recipe_spec')!r}")
        if (r.get("prep_minutes") is None) != (r.get("cook_minutes") is None):
            problems.append(f"recipe {rid}: only one of prep_minutes / cook_minutes is set")
        for o in r.get("meat_types") or []:
            if o not in MEAT_TYPES:
                problems.append(f"recipe {rid}: unknown meat_type {o!r}")
        side = r.get("side_dish")
        for field, value in [("main_ingredient", m) for m in main_ingredients(r.get("main_ingredient"))] \
                + ([("side_dish", side)] if side not in (None, NOT_SPECIFIC) else []):    # None = keine Hauptzutat / Beilage
            if value not in ingredient_ids:
                problems.append(f"recipe {rid}: {field} {value!r} is not an ingredient_id")
            elif (rid, value) not in links:
                problems.append(f"recipe {rid}: {field} {value} is not in its ingredient list")

    recipe_ids = {r.get("recipe_id") for r in data.get("recipes", [])}
    lo, hi = DEFAULT_RATING_SCALE
    for d in data.get("default_ratings", []):
        rid = d.get("recipe_id")
        if rid not in recipe_ids:
            problems.append(f"default_ratings: recipe {rid!r} does not exist")
        for k in DEFAULT_RATING_KEYS:
            v = d.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi):
                problems.append(f"default_ratings: recipe {rid}: {k} must be {lo}-{hi} or null")
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

def user_file(user_dir: Path, user_id) -> Path:
    """Datei mit history + default_ratings eines Users (user_dir = server_data/user_data)."""
    return Path(user_dir) / f"user_{user_id}.yaml"


def load_user_file(path: Path) -> dict:
    """{history, default_ratings} eines Users - fehlt die Datei (neuer User), beides leer."""
    doc = load_yaml(path) if Path(path).exists() else {}
    return {key: doc.get(key) or [] for key in USER_KEYS}


def save_user_file(path: Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(USER_FILE_HEADER)
        yaml.safe_dump({key: data.get(key) or [] for key in USER_KEYS}, f, sort_keys=False, allow_unicode=True)


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