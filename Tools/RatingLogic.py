from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Optional
import random

from Tools import YamlEditor as yr

# Gewichtung fuer den Gesamt-Score einer Bewertung (taste_rating / repeat_rating / effort_rating je 1-5).
# repeat_rating = "wie gerne wuerde man das Gericht bald wieder essen" -> ersetzt ein reines
# Tage-seit-zuletzt-gekocht Kriterium in der Vorschlagslogik (siehe recipe_scores/weighted_shuffle).
# effort_rating = gefuehlter Aufwand (z.B. Anzahl Toepfe/Handgriffe), 5 = wenig Aufwand.
# Das ist NICHT die gemessene Koch-/Vorbereitungszeit, sondern eine rein subjektive
# User-Einschaetzung, unabhaengig von actual_prep/actual_cook.
TASTE_WEIGHT = 0.5
REPEAT_WEIGHT = 0.3
EFFORT_WEIGHT = 0.2

DEFAULT_SCORE = 3.0  # Score fuer Rezepte ohne jede Bewertung (neutral, weder bevorzugt noch benachteiligt)
MIN_WEIGHT = 0.2      # Rezepte mit sehr schlechtem Score sollen trotzdem noch (selten) vorkommen

COOK_LOG_MAX = 20  # rollierendes Zeiten-Log pro Rezept (siehe record_cook_time) - aeltester Eintrag faellt raus


def round_to_10(minutes: float) -> int:
    return int(round(minutes / 10.0) * 10)


def compute_score(taste_rating: Optional[int], repeat_rating: Optional[int], effort_rating: Optional[int]) -> Optional[float]:
    if taste_rating is None or repeat_rating is None or effort_rating is None:
        return None
    return round(
        taste_rating * TASTE_WEIGHT + repeat_rating * REPEAT_WEIGHT + effort_rating * EFFORT_WEIGHT,
        2,
    )


def _new_history_entry(history: list, recipe_id: int, user_id, type_: str, **extra) -> dict:
    """Basis-history-Eintrag (history_id/recipe_id/user_id/date/type). Felder in extra
    (prep_minutes, taste_rating, ...) werden nur gespeichert, wenn sie tatsaechlich einen
    Wert haben - nicht anwendbare Felder (z.B. Zeiten bei einem reinen 'cooked'-Log) werden
    einfach weggelassen statt explizit auf null gesetzt."""
    entry = {
        "history_id": yr.next_id({"history": history}, "history", "history_id"),
        "recipe_id": recipe_id,
        "user_id": user_id,
        "date": date.today().isoformat(),
        "type": type_,
    }
    entry.update({k: v for k, v in extra.items() if v is not None})
    return entry


def _find_recipe(data: dict, recipe_id: int) -> dict:
    recipe = next((r for r in data.get("recipes", []) if r.get("recipe_id") == recipe_id), None)
    if recipe is None:
        raise ValueError(f"recipe {recipe_id} not found")
    return recipe


def last_actual_times(data: dict, recipe_id: int) -> dict:
    """Letzter Zeiten-Eintrag aus dem rollierenden cook_log des Rezepts, zum Vorbefuellen
    des Bewertungsformulars - falls das Rezept schonmal gekocht wurde."""
    recipe = _find_recipe(data, recipe_id)
    log = recipe.get("cook_log") or []
    if not log:
        return {"prep_minutes": None, "cook_minutes": None}
    last = log[-1]
    return {"prep_minutes": last.get("prep_minutes"), "cook_minutes": last.get("cook_minutes")}


def is_wishlisted(data: dict, recipe_id: int, user_id) -> bool:
    """User-abhaengige 'Auf demnaechst setzen'-Wunschliste, gespeichert als eigener
    history-Eintrag (type: 'wishlist') - gleiche Struktur wie 'cooked'/'rated', damit sie
    genauso user-abhaengig abfragbar ist."""
    return any(
        h.get("recipe_id") == recipe_id and h.get("type") == "wishlist" and str(h.get("user_id")) == str(user_id)
        for h in data.get("history", [])
    )


def add_wishlist(data: dict, recipe_id: int, user_id) -> Optional[dict]:
    _find_recipe(data, recipe_id)
    if is_wishlisted(data, recipe_id, user_id):
        return None
    history = data.setdefault("history", [])
    entry = _new_history_entry(history, recipe_id, user_id, "wishlist")
    history.append(entry)
    return entry


def remove_wishlist(data: dict, recipe_id: int, user_id) -> bool:
    before = data.get("history", [])
    after = [
        h for h in before
        if not (h.get("recipe_id") == recipe_id and h.get("type") == "wishlist" and str(h.get("user_id")) == str(user_id))
    ]
    data["history"] = after
    return len(after) != len(before)


def toggle_wishlist(data: dict, recipe_id: int, user_id) -> bool:
    """Fuegt den Wunschlisten-Eintrag hinzu oder entfernt ihn. Rueckgabe: neuer Zustand (True = jetzt gewuenscht)."""
    if is_wishlisted(data, recipe_id, user_id):
        remove_wishlist(data, recipe_id, user_id)
        return False
    add_wishlist(data, recipe_id, user_id)
    return True


def has_cooked(data: dict, recipe_id: int, user_id) -> bool:
    """Hat dieser User dieses Rezept schonmal gekocht oder bewertet? Steuert, ob 'Einmal
    gekocht' beim allerersten Mal direkt auf die Bewertungsseite fuehrt (siehe /rating) -
    ohne diese History gibt es noch keine Referenzzeiten, die zu sammeln sich lohnt."""
    return any(
        h.get("recipe_id") == recipe_id and h.get("type") in ("cooked", "rated") and str(h.get("user_id")) == str(user_id)
        for h in data.get("history", [])
    )


def log_cooked(data: dict, recipe_id: int, user_id) -> dict:
    """'Einmal gekocht'-Button: User + Datum in history vermerken, keine Bewertung. Traegt
    trotzdem einen Zeit-Eintrag ins rollierende cook_log des Rezepts ein (mit dem bisherigen
    Mittelwert als Platzhalter), siehe record_cook_time."""
    recipe = _find_recipe(data, recipe_id)  # 404 schon hier, bevor irgendwas geschrieben wird
    record_cook_time(recipe, None, None)

    history = data.setdefault("history", [])
    entry = _new_history_entry(history, recipe_id, user_id, "cooked")
    history.append(entry)
    return entry


def _log_average(log: list, key: str, fallback) -> Optional[float]:
    values = [e[key] for e in log if e.get(key) is not None]
    if not values:
        return fallback
    return sum(values) / len(values)


def record_cook_time(recipe: dict, actual_prep: Optional[int], actual_cook: Optional[int]) -> None:
    """Haengt einen Zeit-Eintrag an das rollierende cook_log des Rezepts (max COOK_LOG_MAX
    Eintraege - der aelteste faellt beim naechsten Kochen raus) und leitet recipe.prep_minutes/
    cook_minutes als gerundeten Mittelwert ueber das ganze Log neu her.

    Wird kein tatsaechlicher Wert mitgegeben (z.B. beim schnellen 'Einmal gekocht'-Log ohne
    Formular), wird stattdessen der bisherige Mittelwert eingetragen - nur das Datum ist dann
    wirklich neu. Da der bisherige Mittelwert selbst wieder in den Mittelwert eingeht, aendert
    das den Durchschnitt nicht, belegt aber (bewusst) einen der 20 Slots.
    """
    log = recipe.setdefault("cook_log", [])

    prep = actual_prep if actual_prep is not None else _log_average(log, "prep_minutes", recipe.get("prep_minutes"))
    cook = actual_cook if actual_cook is not None else _log_average(log, "cook_minutes", recipe.get("cook_minutes"))

    log.append({"date": date.today().isoformat(), "prep_minutes": prep, "cook_minutes": cook})
    if len(log) > COOK_LOG_MAX:
        del log[0]

    if prep is not None:
        recipe["prep_minutes"] = round_to_10(_log_average(log, "prep_minutes", prep))
    if cook is not None:
        recipe["cook_minutes"] = round_to_10(_log_average(log, "cook_minutes", cook))


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
    - Zeiten werden auf dem Ziel-Rezept (Original oder neue Variante) fortgeschrieben,
      siehe record_cook_time (rollierendes 20er-Log pro Rezept).
    - taste_rating/repeat_rating/effort_rating (je 1-5) ergeben den history-Score, siehe
      compute_score. effort_rating ist eine subjektive Aufwands-Einschaetzung des Users
      (z.B. Anzahl Toepfe/Handgriffe) und unabhaengig von actual_prep/actual_cook.

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
            **{k: v for k, v in recipe.items() if k not in ("recipe_id", "name", "variant_of", "cook_log")},
            "recipe_id": new_id,
            "name": variant_name.strip(),
            "variant_of": main_id,
            "cook_log": [],  # eigenstaendiges Log - nicht die (mutable) Liste des Original-Rezepts teilen
        }
        recipes.append(new_variant)
        target_recipe = new_variant
        _replace_recipe_ingredients(data, new_id, ingredient_overrides)
    elif ingredient_overrides is not None:
        _replace_recipe_ingredients(data, recipe_id, ingredient_overrides)

    record_cook_time(target_recipe, actual_prep, actual_cook)

    history = data.setdefault("history", [])
    entry = _new_history_entry(
        history, target_recipe["recipe_id"], user_id, "rated",
        taste_rating=taste_rating,
        repeat_rating=repeat_rating,
        effort_rating=effort_rating,
        score=compute_score(taste_rating, repeat_rating, effort_rating),
    )
    history.append(entry)

    return {"history_entry": entry, "recipe": target_recipe, "new_variant": new_variant}


def recipe_scores(data: dict, user_id=None) -> dict:
    """recipe_id -> Durchschnitts-Score ueber alle bewerteten history-Eintraege.
    Mit user_id gefiltert auf den jeweiligen User (fuer user-abhaengige Vorschlaege),
    sonst ueber alle User."""
    sums = defaultdict(float)
    counts = defaultdict(int)
    for h in data.get("history", []):
        if h.get("score") is None:
            continue
        if user_id is not None and str(h.get("user_id")) != str(user_id):
            continue
        sums[h["recipe_id"]] += h["score"]
        counts[h["recipe_id"]] += 1
    return {rid: sums[rid] / counts[rid] for rid in sums}


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
