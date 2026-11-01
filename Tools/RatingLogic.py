from __future__ import annotations
from datetime import date
from typing import Optional
import math

from Tools import YamlEditor as yr

# Pro Rezept gibt es GENAU EINEN history-Eintrag (Key: recipe_id). taste_rating/repeat_rating/
# effort_rating/prep_minutes/cook_minutes/dates sind darin je ein rollierendes Array - beim
# naechsten Eintrag faellt bei allen gemeinsam der aelteste Wert raus (siehe _push_rotating).
# So bleiben die Arrays synchron: Index i in jedem Array gehoert zur selben Bewertung.
# dates enthaelt JEDES Kochen (auch 'Einmal gekocht' ohne Bewertung, dort sind die anderen
# Arrays an diesem Index None) - date_score braucht die letzten 20 Koch-Daten fuer mean/std.
# Skalen: taste_rating 0-10 (10 = super lecker), repeat_rating 0-10 (5 = neutral),
# effort_rating 0-10 (0 = sehr einfach, 10 = sehr aufwendig; alte 1-5 Werte umgerechnet mit (x - 1) * 2.5).
HISTORY_ARRAY_MAX = 20
RATING_KEYS = ("taste_rating", "repeat_rating", "effort_rating", "prep_minutes", "cook_minutes")
RATING_SCALE = (0, 10)    # taste, repeat und effort
NEUTRAL_RATING = 5        # Vorbefuellung ohne bisherige Bewertung


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


# Wunschliste ('Auf demnaechst setzen', wishlist.yaml) und Blacklist ('Nicht mehr vorschlagen',
# blacklist.yaml) sind user-abhaengige Listen mit gleichem Aufbau: {recipe_id, user_id, date}.
# Ein Rezept steht pro User hoechstens auf einer der beiden - Hinzufuegen nimmt es von der anderen.
USER_LISTS = ("wishlist", "blacklist")


def _on_list(data: dict, key: str, recipe_id: int, user_id) -> bool:
    return any(
        w.get("recipe_id") == recipe_id and str(w.get("user_id")) == str(user_id)
        for w in data.get(key, [])
    )


def _add_to_list(data: dict, key: str, recipe_id: int, user_id) -> Optional[dict]:
    _find_recipe(data, recipe_id)
    for other in USER_LISTS:
        if other != key:
            _remove_from_list(data, other, recipe_id, user_id)
    if _on_list(data, key, recipe_id, user_id):
        return None
    entry = {"recipe_id": recipe_id, "user_id": user_id, "date": date.today().isoformat()}
    data.setdefault(key, []).append(entry)
    return entry


def _remove_from_list(data: dict, key: str, recipe_id: int, user_id) -> bool:
    before = data.get(key, [])
    after = [
        w for w in before
        if not (w.get("recipe_id") == recipe_id and str(w.get("user_id")) == str(user_id))
    ]
    data[key] = after
    return len(after) != len(before)


def _toggle_list(data: dict, key: str, recipe_id: int, user_id) -> bool:
    """Fuegt den Eintrag hinzu oder entfernt ihn. Rueckgabe: neuer Zustand (True = jetzt auf der Liste)."""
    if _on_list(data, key, recipe_id, user_id):
        _remove_from_list(data, key, recipe_id, user_id)
        return False
    _add_to_list(data, key, recipe_id, user_id)
    return True


def is_wishlisted(data: dict, recipe_id: int, user_id) -> bool:
    return _on_list(data, "wishlist", recipe_id, user_id)


def add_wishlist(data: dict, recipe_id: int, user_id) -> Optional[dict]:
    return _add_to_list(data, "wishlist", recipe_id, user_id)


def remove_wishlist(data: dict, recipe_id: int, user_id) -> bool:
    return _remove_from_list(data, "wishlist", recipe_id, user_id)


def toggle_wishlist(data: dict, recipe_id: int, user_id) -> bool:
    return _toggle_list(data, "wishlist", recipe_id, user_id)


def is_blacklisted(data: dict, recipe_id: int, user_id) -> bool:
    return _on_list(data, "blacklist", recipe_id, user_id)


def toggle_blacklist(data: dict, recipe_id: int, user_id) -> bool:
    """'Nicht mehr vorschlagen': ProposeLogic.hard_filter wirft das Rezept fuer diesen User raus."""
    if user_id in (None, ""):
        raise ValueError("user_id required for the blacklist")
    return _toggle_list(data, "blacklist", recipe_id, user_id)


def has_cooked(data: dict, recipe_id: int) -> bool:
    """Wurde dieses Rezept schonmal wirklich gekocht (last_date gesetzt)? Ein reiner
    dismiss-Eintrag (siehe log_dismissed) zaehlt NICHT, weil der
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
    zum Vorbefuellen der Bewertungsseite. Ohne jede history: neutraler Default (Mitte 5 auf
    den 0-10 Skalen). Die *_avg Werte sind die ungerundeten Mittelwerte, fuer eine
    optionale Halb-Stern-Anzeige."""
    entry = _find_history_entry(data, recipe_id)
    taste_avg = _ceil_avg(entry.get("taste_rating", []) if entry else [])
    repeat_avg = _ceil_avg(entry.get("repeat_rating", []) if entry else [])
    effort_avg = _ceil_avg(entry.get("effort_rating", []) if entry else [])
    return {
        "taste_rating": math.ceil(taste_avg) if taste_avg is not None else NEUTRAL_RATING,
        "repeat_rating": math.ceil(repeat_avg) if repeat_avg is not None else NEUTRAL_RATING,
        "effort_rating": math.ceil(effort_avg) if effort_avg is not None else NEUTRAL_RATING,
        "taste_rating_avg": taste_avg,
        "repeat_rating_avg": repeat_avg,
        "effort_rating_avg": effort_avg,
    }


def log_dismissed(data: dict, recipe_id: int) -> dict:
    """'Nicht interessiert'-Button beim Vorschlag (/api/dismiss): senkt den Wiederholungs-
    Wunsch fuer dieses Rezept mit dem niedrigsten repeat_rating=0 - unabhaengig davon, ob
    das Rezept schonmal gekocht wurde. Haengt nur an repeat_rating an, ohne dates/last_date
    oder die anderen Arrays anzufassen."""
    _find_recipe(data, recipe_id)
    entry = _get_or_create_history_entry(data, recipe_id)
    _push_rotating(entry, "repeat_rating", 0)
    return entry


def _cooked_today_unrated(entry: dict, today: str) -> bool:
    """Wurde heute schon per log_cooked ein dates-Eintrag ohne Bewertung angelegt?"""
    dates = entry.get("dates") or []
    return bool(dates) and dates[-1] == today and all(
        (entry.get(k) or [None])[-1] is None for k in RATING_KEYS
    )


def log_cooked(data: dict, recipe_id: int, user_id) -> dict:
    """'Einmal gekocht'-Button: setzt last_date und haengt heute an dates an (keine
    Bewertung - die anderen Arrays bekommen an diesem Index None, damit sie synchron bleiben).
    Zweimal am selben Tag ergibt nur einen dates-Eintrag. Ein Rezept, das gerade gekocht
    wurde, muss nicht mehr auf der Wunschliste stehen - wird also automatisch entfernt."""
    _find_recipe(data, recipe_id)  # 404 schon hier, bevor irgendwas geschrieben wird
    remove_wishlist(data, recipe_id, user_id)

    today = date.today().isoformat()
    entry = _get_or_create_history_entry(data, recipe_id)
    entry["last_date"] = today
    if not _cooked_today_unrated(entry, today):
        _push_rotating(entry, "dates", today)
        for key in RATING_KEYS:
            _push_rotating(entry, key, None)
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
    Teilbewertungen sind nicht erlaubt: taste/repeat/effort muessen alle gesetzt sein (0-10),
    Zeiten entweder beide oder keine (ValueError).
    """
    lo, hi = RATING_SCALE
    for key, value in (("taste_rating", taste_rating), ("repeat_rating", repeat_rating),
                       ("effort_rating", effort_rating)):
        if value is None or not lo <= value <= hi:
            raise ValueError(f"{key} required ({lo}-{hi})")
    if (actual_prep is None) != (actual_cook is None):
        raise ValueError("actual_prep and actual_cook: give both or none")

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
    ratings = {
        "taste_rating": taste_rating,
        "repeat_rating": repeat_rating,
        "effort_rating": effort_rating,
        "prep_minutes": actual_prep,
        "cook_minutes": actual_cook,
    }
    if _cooked_today_unrated(entry, today):
        # heute schon per 'Einmal gekocht' erfasst -> diesen Index fuellen statt ein zweites
        # Datum anzulegen (sonst entstuende ein 0-Tage-Abstand in dates)
        for key, value in ratings.items():
            entry[key][-1] = value
    else:
        _push_rotating(entry, "dates", today)
        for key, value in ratings.items():
            _push_rotating(entry, key, value)
    entry["last_date"] = today

    update_recipe_times(data, target_recipe)

    return {"history_entry": entry, "recipe": target_recipe, "new_variant": new_variant}
