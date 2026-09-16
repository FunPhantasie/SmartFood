from __future__ import annotations
from datetime import date
from typing import Optional
import math
import random

from Tools import YamlEditor as yr

DEFAULT_SCORE = 3.0  # Score fuer Rezepte ohne jede Bewertung (neutral, weder bevorzugt noch benachteiligt)
MIN_WEIGHT = 0.2      # Rezepte mit sehr schlechtem Score sollen trotzdem noch (selten) vorkommen

# Pro Rezept gibt es GENAU EINEN history-Eintrag (Key: recipe_id). taste_rating/repeat_rating/
# effort_rating/prep_minutes/cook_minutes/dates sind darin je ein rollierendes Array - beim
# naechsten Eintrag faellt bei allen gemeinsam der aelteste Wert raus (siehe _push_rotating).
# So bleiben die Arrays synchron: Index i in jedem Array gehoert zur selben Bewertung.
HISTORY_ARRAY_MAX = 20


def round_to_10(minutes: float) -> int:
    """Rundet immer klassisch (5 -> 10, nicht 5 -> 0) - Pythons round() rundet .5 sonst
    zur naechsten geraden Zahl (banker's rounding), was bei /10-Mittelwerten wie 0.5
    unerwartet auf 0 statt 10 rundet."""
    return int(math.floor(minutes / 10.0 + 0.5) * 10)


def _find_recipe(data: dict, recipe_id: int) -> dict:
    recipe = next((r for r in data.get("recipes", []) if r.get("recipe_id") == recipe_id), None)
    if recipe is None:
        raise ValueError(f"recipe {recipe_id} not found")
    return recipe


def _find_history_entry(data: dict, recipe_id: int) -> Optional[dict]:
    return next((h for h in data.get("history", []) if h.get("recipe_id") == recipe_id), None)


def _get_or_create_history_entry(data: dict, recipe_id: int) -> dict:
    entry = _find_history_entry(data, recipe_id)
    if entry is not None:
        return entry
    history = data.setdefault("history", [])
    entry = {"recipe_id": recipe_id}
    history.append(entry)
    return entry


def _push_rotating(entry: dict, key: str, value) -> None:
    """Haengt value an entry[key] an (legt das Array bei Bedarf an) und kickt den aeltesten
    Wert raus, sobald HISTORY_ARRAY_MAX ueberschritten wird."""
    arr = entry.setdefault(key, [])
    arr.append(value)
    if len(arr) > HISTORY_ARRAY_MAX:
        del arr[0]


def is_wishlisted(data: dict, recipe_id: int, user_id) -> bool:
    """User-abhaengige 'Auf demnaechst setzen'-Wunschliste - eigene Collection (wishlist.yaml,
    Key 'wishlist'), getrennt von der eigentlichen Koch-/Bewertungs-history."""
    return any(
        w.get("recipe_id") == recipe_id and str(w.get("user_id")) == str(user_id)
        for w in data.get("wishlist", [])
    )


def add_wishlist(data: dict, recipe_id: int, user_id) -> Optional[dict]:
    _find_recipe(data, recipe_id)
    if is_wishlisted(data, recipe_id, user_id):
        return None
    wishlist = data.setdefault("wishlist", [])
    entry = {"recipe_id": recipe_id, "user_id": user_id, "date": date.today().isoformat()}
    wishlist.append(entry)
    return entry


def remove_wishlist(data: dict, recipe_id: int, user_id) -> bool:
    before = data.get("wishlist", [])
    after = [
        w for w in before
        if not (w.get("recipe_id") == recipe_id and str(w.get("user_id")) == str(user_id))
    ]
    data["wishlist"] = after
    return len(after) != len(before)


def toggle_wishlist(data: dict, recipe_id: int, user_id) -> bool:
    """Fuegt den Wunschlisten-Eintrag hinzu oder entfernt ihn. Rueckgabe: neuer Zustand (True = jetzt gewuenscht)."""
    if is_wishlisted(data, recipe_id, user_id):
        remove_wishlist(data, recipe_id, user_id)
        return False
    add_wishlist(data, recipe_id, user_id)
    return True


def has_cooked(data: dict, recipe_id: int) -> bool:
    """Wurde dieses Rezept schonmal wirklich gekocht (last_date gesetzt)? Ein reiner
    dismiss/seed-Eintrag (siehe log_dismissed/ensure_uncooked_seed) zaehlt NICHT, weil der
    kein last_date setzt - nur rate_recipe/log_cooked tun das."""
    entry = _find_history_entry(data, recipe_id)
    return bool(entry and entry.get("last_date"))


def last_actual_times(data: dict, recipe_id: int) -> dict:
    """Letzter gemessener Zeiten-Eintrag dieses Rezepts (Ende der rollierenden Arrays), zum
    Vorbefuellen des Bewertungsformulars - falls das Rezept schonmal mit Zeiten bewertet wurde."""
    entry = _find_history_entry(data, recipe_id)
    prep = [v for v in (entry.get("prep_minutes", []) if entry else []) if v is not None]
    cook = [v for v in (entry.get("cook_minutes", []) if entry else []) if v is not None]
    return {
        "prep_minutes": prep[-1] if prep else None,
        "cook_minutes": cook[-1] if cook else None,
    }


def _ceil_avg(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def default_ratings(data: dict, recipe_id: int) -> dict:
    """Durchschnitt der letzten Bewertungen dieses Rezepts (aufgerundet auf ganze Sterne),
    zum Vorbefuellen der Bewertungsseite. Ohne jede history: neutraler Default (3). Die
    *_avg Werte sind die ungerundeten Mittelwerte, fuer eine optionale Halb-Stern-Anzeige."""
    entry = _find_history_entry(data, recipe_id)
    taste_avg = _ceil_avg(entry.get("taste_rating", []) if entry else [])
    repeat_avg = _ceil_avg(entry.get("repeat_rating", []) if entry else [])
    effort_avg = _ceil_avg(entry.get("effort_rating", []) if entry else [])
    return {
        "taste_rating": math.ceil(taste_avg) if taste_avg is not None else 3,
        "repeat_rating": math.ceil(repeat_avg) if repeat_avg is not None else 3,
        "effort_rating": math.ceil(effort_avg) if effort_avg is not None else 3,
        "taste_rating_avg": taste_avg,
        "repeat_rating_avg": repeat_avg,
        "effort_rating_avg": effort_avg,
    }


def _log_low_repeat(data: dict, recipe_id: int, value: int = 1) -> dict:
    """Haengt value ans rollierende repeat_rating-Array des Rezepts an - ohne dates/last_date
    oder die anderen Arrays anzufassen. Gemeinsame Basis fuer log_dismissed (User lehnt
    Vorschlag ab) und ensure_uncooked_seed (Rezept ganz ohne history)."""
    _find_recipe(data, recipe_id)
    entry = _get_or_create_history_entry(data, recipe_id)
    _push_rotating(entry, "repeat_rating", value)
    return entry


def log_dismissed(data: dict, recipe_id: int) -> dict:
    """'Nicht interessiert'-Button beim Vorschlag (/api/dismiss): senkt den Wiederholungs-
    Wunsch fuer dieses Rezept mit einem niedrigen repeat_rating=1 - unabhaengig davon, ob
    das Rezept schonmal gekocht wurde."""
    return _log_low_repeat(data, recipe_id, 1)


def ensure_uncooked_seed(data: dict, recipe_id: int) -> Optional[dict]:
    """Falls dieses Rezept noch KEINEN history-Eintrag hat (noch nie gekocht/bewertet/
    dismissed), wird ein initialer Eintrag mit repeat_rating=1 angelegt - damit ein komplett
    unerprobtes Rezept in einer history-basierten Auswertung nicht wie ein neutral bewaehrtes
    (DEFAULT_SCORE) behandelt wird. Gibt den neuen Eintrag zurueck, oder None wenn bereits
    history existiert."""
    if _find_history_entry(data, recipe_id) is not None:
        return None
    return _log_low_repeat(data, recipe_id, 1)


def log_cooked(data: dict, recipe_id: int, user_id) -> dict:
    """'Einmal gekocht'-Button: aktualisiert NUR last_date (keine Bewertung, keine Zeiten,
    kein neuer dates-Eintrag - der dates-Array-Eintrag ist rate_recipe vorbehalten). Ein
    Rezept, das gerade gekocht wurde, muss nicht mehr auf der Wunschliste stehen - wird also
    automatisch entfernt."""
    _find_recipe(data, recipe_id)  # 404 schon hier, bevor irgendwas geschrieben wird
    remove_wishlist(data, recipe_id, user_id)

    entry = _get_or_create_history_entry(data, recipe_id)
    entry["last_date"] = date.today().isoformat()
    return entry


def update_recipe_times(data: dict, recipe: dict) -> None:
    """Leitet recipe.prep_minutes/cook_minutes als gerundeten Mittelwert ueber die
    rollierenden Zeiten-Arrays des Rezepts neu her (schon durch _push_rotating auf die
    letzten HISTORY_ARRAY_MAX Eintraege begrenzt). Ein Rezept ohne jede Zeiten-history
    behaelt einfach seinen letzten/initialen Wert."""
    entry = _find_history_entry(data, recipe["recipe_id"])
    if entry is None:
        return
    prep_values = [v for v in entry.get("prep_minutes", []) if v is not None]
    cook_values = [v for v in entry.get("cook_minutes", []) if v is not None]

    if prep_values:
        recipe["prep_minutes"] = round_to_10(sum(prep_values) / len(prep_values))
    if cook_values:
        recipe["cook_minutes"] = round_to_10(sum(cook_values) / len(cook_values))


def _replace_recipe_ingredients(data: dict, recipe_id: int, ingredient_overrides: list[dict]) -> None:
    recipe_ingredients = data.setdefault("recipe_ingredients", [])
    data["recipe_ingredients"] = [ri for ri in recipe_ingredients if ri.get("recipe_id") != recipe_id]
    for ov in ingredient_overrides:
        data["recipe_ingredients"].append({
            "recipe_id": recipe_id,
            "ingredient_id": ov["ingredient_id"],
            "quantity": ov.get("quantity"),
            "unit": ov.get("unit"),
        })


def rate_recipe(
    data: dict,
    recipe_id: int,
    user_id,
    *,
    actual_prep: Optional[int] = None,
    actual_cook: Optional[int] = None,
    taste_rating: Optional[int] = None,
    repeat_rating: Optional[int] = None,
    effort_rating: Optional[int] = None,
    ingredient_overrides: Optional[list[dict]] = None,
    save_as_variant: bool = False,
    variant_name: Optional[str] = None,
) -> dict:
    """Volle Bewertung ueber 'Gekocht & bewerten'.

    - Zutaten-Abweichungen (ingredient_overrides) werden entweder direkt in das gekochte
      Rezept uebernommen (save_as_variant=False) oder als neue Variante mit eigenem Namen
      gespeichert (save_as_variant=True, variant_name erforderlich).
    - Es gibt GENAU EINEN history-Eintrag pro Rezept (siehe _get_or_create_history_entry).
      Jede Bewertung haengt einen Wert an die rollierenden Arrays (dates, taste_rating,
      repeat_rating, effort_rating, prep_minutes, cook_minutes) und setzt last_date -
      aelteste Werte fallen ab HISTORY_ARRAY_MAX raus (_push_rotating). prep_minutes/
      cook_minutes des Ziel-Rezepts (Original oder neue Variante) werden danach als
      Mittelwert ueber die Arrays neu berechnet, siehe update_recipe_times.
    - Das Original-Rezept wird fuer diesen User von der Wunschliste entfernt (es wurde ja
      gerade gekocht).

    Rueckgabe: {"history_entry", "recipe", "new_variant"} - new_variant ist None, wenn
    keine neue Variante angelegt wurde.
    """
    recipe = _find_recipe(data, recipe_id)
    recipes = data.setdefault("recipes", [])

    new_variant = None
    target_recipe = recipe

    if ingredient_overrides is not None and save_as_variant:
        if not variant_name or not variant_name.strip():
            raise ValueError("variant_name required when save_as_variant=True")

        main_id = recipe.get("variant_of") or recipe.get("recipe_id")
        new_id = yr.next_id({"recipes": recipes}, "recipes", "recipe_id")
        new_variant = {
            **{k: v for k, v in recipe.items() if k not in ("recipe_id", "name", "variant_of")},
            "recipe_id": new_id,
            "name": variant_name.strip(),
            "variant_of": main_id,
        }
        recipes.append(new_variant)
        target_recipe = new_variant
        _replace_recipe_ingredients(data, new_id, ingredient_overrides)
    elif ingredient_overrides is not None:
        _replace_recipe_ingredients(data, recipe_id, ingredient_overrides)

    remove_wishlist(data, recipe_id, user_id)

    today = date.today().isoformat()
    entry = _get_or_create_history_entry(data, target_recipe["recipe_id"])
    _push_rotating(entry, "dates", today)
    entry["last_date"] = today
    _push_rotating(entry, "taste_rating", taste_rating)
    _push_rotating(entry, "repeat_rating", repeat_rating)
    _push_rotating(entry, "effort_rating", effort_rating)
    _push_rotating(entry, "prep_minutes", actual_prep)
    _push_rotating(entry, "cook_minutes", actual_cook)

    update_recipe_times(data, target_recipe)

    return {"history_entry": entry, "recipe": target_recipe, "new_variant": new_variant}


def recipe_scores(data: dict) -> dict:
    """recipe_id -> durchschnittliche taste_rating ueber die history dieses Rezepts. Seit
    der kombinierte 'score' (compute_score) auf Wunsch entfernt wurde, ist das die einzige
    verbliebene Naeherung fuer weighted_shuffle - reine Uebergangsloesung, bis die neue
    Propose-Mechanik (siehe ProposeLogic.build_propose_dataset) das ersetzt."""
    scores = {}
    for h in data.get("history", []):
        values = [v for v in h.get("taste_rating", []) if v is not None]
        if values:
            scores[h["recipe_id"]] = sum(values) / len(values)
    return scores


def weighted_shuffle(recipes: list[dict], scores: dict, id_key: str = "recipe_id") -> list[dict]:
    """Zufalls-Reihenfolge, aber Rezepte mit hoeherem Bewertungs-Score kommen tendenziell
    weiter vorne. Unbewertete Rezepte bekommen DEFAULT_SCORE (neutral)."""
    pool = list(recipes)
    weights = [max(scores.get(r.get(id_key), DEFAULT_SCORE), MIN_WEIGHT) for r in pool]

    out = []
    while pool:
        total = sum(weights)
        pick = random.uniform(0, total)
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if pick <= acc:
                out.append(pool.pop(i))
                weights.pop(i)
                break
    return out
