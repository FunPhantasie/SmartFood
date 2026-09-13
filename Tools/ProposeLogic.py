from __future__ import annotations
from typing import Optional


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
