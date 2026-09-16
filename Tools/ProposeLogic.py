from __future__ import annotations
from collections import defaultdict
from typing import Optional

from Tools import RatingLogic as rl


def build_propose_dataset(data: dict) -> dict:
    """Grunddaten fuer die naechste Propose-Mechanik: pro Rezept-ID (= 'die Keys') das
    Rezept selbst, seine komplette history und die verknuepften Zutaten (recipe_ingredients).
    Rezepte ganz ohne history bekommen hier einen niedrigen Seed-Eintrag (repeat_rating=1,
    siehe RatingLogic.ensure_uncooked_seed), damit sie in einer history-basierten Auswertung
    nicht wie neutral-bewaehrte Rezepte (DEFAULT_SCORE) behandelt werden - dieser Aufruf
    schreibt also in data['history'], nicht nur lesend.

    Baut noch KEINE Gewichtung/Auswahl - das ist der naechste Schritt fuer die eigentliche
    Vorschlags-Logik, die on top von diesem Dataset gebaut wird.

    Rueckgabe: {recipe_id: {"recipe": {...}, "history": [...], "ingredients": [...]}}
    """
    recipes = data.get("recipes", [])
    history = data.get("history", [])
    recipe_ingredients = data.get("recipe_ingredients", [])

    history_by_recipe: dict = defaultdict(list)
    for h in history:
        history_by_recipe[h.get("recipe_id")].append(h)

    ingredients_by_recipe: dict = defaultdict(list)
    for ri in recipe_ingredients:
        ingredients_by_recipe[ri.get("recipe_id")].append(ri)

    dataset = {}
    for r in recipes:
        rid = r.get("recipe_id")
        if not history_by_recipe.get(rid):
            seed = rl.ensure_uncooked_seed(data, rid)
            if seed is not None:
                history_by_recipe[rid].append(seed)
        dataset[rid] = {
            "recipe": r,
            "history": history_by_recipe.get(rid, []),
            "ingredients": ingredients_by_recipe.get(rid, []),
        }
    return dataset


def recipe_to_frontend(r: dict) -> dict:
    """Convert recipe dict to frontend format"""
    return {
        "id": r.get("recipe_id"),
        "name": r.get("name"),
        "recipe_type": r.get("recipe_type", "-"),
        "veg_type": r.get("veg_type"),
        "prep_t": r.get("prep_minutes", "0"),
        "cook_t": r.get("cook_minutes", "0"),
        "season": r.get("season", "always"),
    }


def filter_recipes(
    recipes: list[dict],
    meal_type: str = "main_dish",
    diet: str = "any",
    include: Optional[list] = None,
    exclude: Optional[list] = None,
) -> list[dict]:
    """
    Zentrale Filter-Logik fuer Rezeptvorschlaege (genutzt von GET und POST /api/propsals).

    HIER ist der Ort, um weitere Filter-Kriterien einzubauen (season, include/exclude
    von Zutaten, History/Bewertung, ...) - einfach unten in der for-Schleife eine
    weitere "continue"-Bedingung ergaenzen. include/exclude werden aktuell schon als
    Parameter durchgereicht, aber noch NICHT ausgewertet - das ist der naechste Schritt.

    Parameter:
      recipes:   Liste aller rohen Rezept-Dicts (direkt aus recipes.yaml, ungefiltert)
      meal_type: gewuenschter recipe_type, z.B. "main_dish", "sweet", "side_dish", ...
      diet:      gewuenschter veg_type ("vegan", "vegetarian", "meat") oder "any"
      include:   Liste von Zutaten-IDs, die im Rezept enthalten sein MUESSEN (noch offen)
      exclude:   Liste von Zutaten-IDs, die NICHT enthalten sein DUERFEN (noch offen)

    Rueckgabe: gefilterte Liste von rohen Rezept-Dicts (noch NICHT frontend-formatiert -
               dafuer nach dem Aufruf recipe_to_frontend() auf jedes Element anwenden).
    """
    include = include or []
    exclude = exclude or []

    filtered = []
    for r in recipes:
        # --- Pflicht-Filter ---
        if r.get("recipe_type") != meal_type:
            continue
        if diet != "any" and r.get("veg_type") != diet:
            continue

        # --- Ab hier weitere Filter ergaenzen, z.B.: ---
        # if r.get("season") not in (gewuenschte_season, "always"): continue
        # if include and nicht alle include-Zutaten im Rezept: continue
        # if exclude and irgendeine exclude-Zutat im Rezept: continue

        filtered.append(r)

    return filtered
