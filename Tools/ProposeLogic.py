from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Optional
import math

from Tools import RatingLogic as rl

# Formeln & Sanity-Checks dazu: docs/ProposeLogic.md


def calcAvgDistanceScore(avg_distance):
    if avg_distance ==0:
        return 0
    return max(0,3-10/avg_distance)


def repeatScore(entry: dict, today: Optional[date] = None) -> float:
    """date_score fuer EINEN history-Eintrag (ein Rezept):
        10 * WDH_Lust/5 * exp(-8/diff_lastcooked * calcAvgDistanceScore(avg_dist))
    today ist injizierbar fuer reproduzierbare Tests (Default: heute)."""
    today = today or date.today()

    dates = sorted(date.fromisoformat(d) for d in entry.get("dates") or [])
    if not dates:
        avg_dist = 1
    else:
        dates.append(today)  # Kopie - die history selbst wird nicht veraendert
        gaps = [(b - a).days for a, b in zip(dates[:-1], dates[1:])]
        avg_dist = sum(gaps) / len(gaps)

    repeats = [v for v in entry.get("repeat_rating") or [] if v is not None]
    WDH_Lust = sum(repeats) / len(repeats) if repeats else 3

    last_date = entry.get("last_date")
    if not last_date:
        return 10 * WDH_Lust / 5  # nie gekocht: diff_lastcooked = unendlich -> exp(0) = 1
    diff_lastcooked = max((today - date.fromisoformat(last_date)).days, 1)  # heute gekocht -> 1 Tag

    return 10 * WDH_Lust / 5 * math.exp(-8 / diff_lastcooked * calcAvgDistanceScore(avg_dist))


# TODO: noch in Arbeit - wird noch nicht aufgerufen (np/softmax fehlen noch)
def dopaminscore(recipes):
    geschmack=recipes.get("geschmack",3)
    aufwand=recipes.get("aufwand",3)
    zeit=recipes.get("cook_time",np.nan)+recipes.get("prep_time",np.nan)
    kochscore=softmax(zeit/7.5)#7,5 Min
    
def build_propose_dataset(data: dict) -> dict:

    recipes = data.get("recipes", [])
    history = data.get("history", [])
    # TODO: tastevsaufwand_score = dopaminscore(...) pro Rezept, sobald fertig
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
        entries = history_by_recipe.get(rid, [])
        dataset[rid] = {
            "recipe": r,
            "history": entries,
            "ingredients": ingredients_by_recipe.get(rid, []),
            # Pro Rezept genau ein history-Eintrag (siehe RatingLogic)
            "date_score": repeatScore(entries[0]) if entries else None,
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
