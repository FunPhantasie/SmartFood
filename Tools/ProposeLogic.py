from __future__ import annotations
from collections import defaultdict
from datetime import date
from typing import Optional
import math
import random

from Tools import RatingLogic as rl

# Formeln, Wertebereiche & Sanity-Checks dazu: docs/ProposeLogic.md
# Beispiel-Szenarien / Logik-Test:             tests/test_propose_plan.py
#
# Aufbau: pro Score eine reine Formel (calc_*, nur Zahlen rein/raus - so testbar) und eine
# Funktion, die die Eingaben aus den echten Daten (history-Eintrag, Rezept) holt.

# ---------------- Stellschrauben ----------------
DATE_SLOPE = 30           # II.1 tanh(factor/DATE_SLOPE · (dist_last - DATE_BLOCK))
DATE_BLOCK = 4            # II.1 innerhalb dieser Tage nach dem Kochen -> remove
NEVER_COOKED_DATE = 5     # II.1 date_score fuer nie gekochte Rezepte
EMPTY_REPEAT = 2          # II.1 repeat, wenn repeat_rating leer ist
COOK_MID = 50             # II.2 timescore = 0.5 bei so vielen Minuten
COOK_UNIT = 7.5           # II.2 Steilheit von timescore
TASTE_EXP = 1.5           # II.2 >1 -> schlechter Geschmack wird haerter bestraft
EFFORT_WEIGHT = 0.5       # II.2 max. Verlust durch Aufwand (bei taste 10 und effort 5)
NEVER_COOKED_TASTE = 8    # II.2 taste ohne Bewertung
NEVER_COOKED_EFFORT = 3   # II.2 effort ohne Bewertung
MISSING_TIME = 45         # II.2 Gesamtzeit, wenn keine Zeiten hinterlegt sind
SAME_DAY_LIMIT = 60       # II.4 prep oder cook >= so viele Minuten -> raus
LAST_SUPPER_SIZE = 3      # II.3 die letzten n gekochten Gerichte ...
LAST_SUPPER_DAYS = 4      # II.3 ... sofern hoechstens so viele Tage her
DAMP_SPECS = {"sweet", "soup", "casserole"}   # II.3 nur diese Specs daempfen
WISHLIST_SCORE = 10       # III  Bonus fuer Rezepte auf der Wunschliste
WISHLIST_UNDAMPED = 5     # III  wishlist_score / WISHLIST_UNDAMPED kommt NACH der Daempfung dazu
SOFTMAX_T = 3             # III  Softmax-Temperatur: klein = die Besten gewinnen fast immer, gross = zufaelliger
SWAP_P5 = 0.8             # III  P(kein Tausch bei 5 Vorschlaegen)
PROPOSAL_COUNT = 5        # III  Anzahl Vorschlaege


def _mean(values) -> Optional[float]:
    values = [v for v in values or [] if v is not None]
    return sum(values) / len(values) if values else None


# ================= II.1 date_score =================
def date_factor(avg_dist: Optional[float]) -> float:
    """1 - 4: 4 = sehr oft gekocht (kommt schneller wieder), 1 = selten oder <= 1 Datum."""
    if avg_dist is None:                       # <= 1 Datum -> noch kein Abstand
        return 1
    return max(1, 4 - math.floor(avg_dist) / 14)


def calc_date_score(repeat: Optional[float], avg_dist: Optional[float],
                    dist_last: Optional[int]) -> tuple[float, bool]:
    """Reine Formel. dist_last=None -> nie gekocht. Rueckgabe (date_score, remove)."""
    if dist_last is None:
        return NEVER_COOKED_DATE, False
    repeat = EMPTY_REPEAT if repeat is None else repeat
    raw = 10 / 5 * repeat * math.tanh(date_factor(avg_dist) / DATE_SLOPE * (dist_last - DATE_BLOCK))
    return max(0.0, raw), raw <= 0


def date_score(entry: Optional[dict], today: Optional[date] = None) -> tuple[float, bool]:
    """date_score fuer EINEN history-Eintrag (ein Rezept). today injizierbar fuer Tests."""
    today = today or date.today()
    entry = entry or {}

    dates = sorted(date.fromisoformat(d) for d in entry.get("dates") or [])   # ohne today
    avg_dist = None
    if len(dates) >= 2:
        gaps = [(b - a).days for a, b in zip(dates[:-1], dates[1:])]
        avg_dist = sum(gaps) / len(gaps)

    last_date = entry.get("last_date")
    dist_last = (today - date.fromisoformat(last_date)).days if last_date else None

    return calc_date_score(_mean(entry.get("repeat_rating")), avg_dist, dist_last)


# ================= II.2 reward_score =================
def timescore(minutes: float) -> float:
    return 1 / (1 + math.exp((minutes - COOK_MID) / COOK_UNIT))


def calc_reward(taste: float, effort: float, minutes: float) -> float:
    """Reine Formel. taste 0-10, effort 1-5 (5 = hoher Aufwand). Ergebnis 0 - 10."""
    taste_part = (taste / 10) ** TASTE_EXP                   # schlechter Geschmack hart bestraft
    cost = (effort - 1) / 4                                  # 0 = wenig, 1 = viel Aufwand
    effort_part = 1 - EFFORT_WEIGHT * (taste / 10) * cost    # Aufwand zaehlt mehr bei leckeren Gerichten
    return 10 * timescore(minutes) * taste_part * effort_part


def total_minutes(recipe: dict) -> float:
    prep, cook = recipe.get("prep_minutes"), recipe.get("cook_minutes")
    if prep is None and cook is None:
        return MISSING_TIME
    return (prep or 0) + (cook or 0)


def reward_score(recipe: dict, entry: Optional[dict]) -> float:
    entry = entry or {}
    taste = _mean(entry.get("taste_rating"))
    effort = _mean(entry.get("effort_rating"))
    return calc_reward(
        NEVER_COOKED_TASTE if taste is None else taste,
        NEVER_COOKED_EFFORT if effort is None else effort,
        total_minutes(recipe),
    )


# ================= II.3 damp_score =================
def current_season(today: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(today.month, "autumn")


def recipe_features(recipe: dict, data: dict) -> dict:
    """Alles, was die Daempfung von einem Rezept braucht. Einzige Stelle, die die Datenfelder
    kennt - fehlende Felder (origin, cooking_method, recipe_spec, main_ingredient) ergeben
    einfach leere Werte, die Regel greift dann nicht.
    Fleischsorten: Zutaten mit veg_type == meat (offene Frage VIII.11 im Doc)."""
    ingredients = {i.get("ingredient_id"): i for i in data.get("ingredients", [])}
    ids = [ri.get("ingredient_id") for ri in data.get("recipe_ingredients", [])
           if ri.get("recipe_id") == recipe.get("recipe_id")]
    origin = recipe.get("origin") or []
    specs = {recipe.get("recipe_spec")} & DAMP_SPECS
    if recipe.get("sweet"):
        specs.add("sweet")
    return {
        "season": recipe.get("season") or "all",
        "origins": set(origin if isinstance(origin, list) else [origin]),
        "method": recipe.get("cooking_method"),
        "specs": specs,
        "sides": {i for i in ids if ingredients.get(i, {}).get("side_dish")},
        "main": recipe.get("main_ingredient"),
        "meats": {i for i in ids if ingredients.get(i, {}).get("veg_type") == "meat"},
    }


def merge_last_supper(features: list[dict]) -> dict:
    """EINE zusammengefuehrte Liste aus allen last_supper-Gerichten (einmal, vor der Schleife)."""
    return {
        "origins": set().union(*(f["origins"] for f in features)),
        "methods": {f["method"] for f in features if f["method"]},
        "specs": set().union(*(f["specs"] for f in features)),
        "sides": set().union(*(f["sides"] for f in features)),
        "mains": {f["main"] for f in features if f["main"]},
        "meats": set().union(*(f["meats"] for f in features)),
    }


def calc_damping(cand: dict, ls: dict, season_now: str) -> tuple[float, float, list[str]]:
    """Reine Formel. Jede Regel prueft nur 'in der Liste: ja / nein' -> max. einmal pro Kandidat.
    Rueckgabe (damp_score_mult, damp_score_offset, getroffene Regeln)."""
    mult, off, log = 1.0, 0, []
    if cand["season"] in ("all", "always", season_now):
        off += 3; log.append("season +3")
    if cand["origins"] & ls["origins"]:
        off -= 1; log.append("origin -1")
    # cooking method doppelt -> bewusst keine Wirkung
    if cand["specs"] & ls["specs"]:
        mult *= 1 - 0.8; log.append("sweet/soup/casserole x0.2")
    if cand["sides"] & ls["sides"]:
        off -= 3; log.append("side -3")
    if cand["meats"]:
        f = 1 - 0.1 * len(ls["meats"])
        mult *= f; log.append(f"meat x{f:.1f}")
    if cand["meats"] & ls["meats"]:
        off -= 5; log.append("same meat -5")
    if cand["main"] and cand["main"] in ls["mains"]:
        if cand["main"] in cand["meats"] or cand["main"] in cand["sides"]:
            mult *= 1 - 0.1; log.append("main=meat/side x0.9")
        else:
            off -= 3; log.append("main -3")
    return mult, off, log


def last_supper(data: dict, today: Optional[date] = None) -> list[int]:
    """recipe_ids der letzten LAST_SUPPER_SIZE gekochten Gerichte, max. LAST_SUPPER_DAYS her."""
    today = today or date.today()
    recent = []
    for h in data.get("history", []):
        if h.get("last_date"):
            days = (today - date.fromisoformat(h["last_date"])).days
            if 0 <= days <= LAST_SUPPER_DAYS:
                recent.append((h["last_date"], h["recipe_id"]))
    recent.sort(reverse=True)
    return [rid for _, rid in recent[:LAST_SUPPER_SIZE]]


# ================= II.4 hard filter =================
def variant_root(recipe: dict) -> int:
    """Original-Rezept einer Variante (oder das Rezept selbst) - Varianten teilen den root."""
    return recipe.get("variant_of") or recipe.get("recipe_id")


def is_same_day(recipe: dict) -> bool:
    return any((recipe.get(k) or 0) >= SAME_DAY_LIMIT for k in ("prep_minutes", "cook_minutes"))


# ================= III total score, draw, swap =================
def calc_total_score(date_s: float, reward_s: float, mult: float, off: float, wishlist: bool) -> float:
    """(date + reward + wishlist) · mult + offset + wishlist / WISHLIST_UNDAMPED"""
    w = WISHLIST_SCORE if wishlist else 0
    return (date_s + reward_s + w) * mult + off + w / WISHLIST_UNDAMPED


def softmax(scores: list[float], t: Optional[float] = None) -> list[float]:
    """p_i = exp(s_i/T) / sum exp(s_j/T). max wird nur fuer numerische Sicherheit abgezogen."""
    t = t or SOFTMAX_T
    m = max(scores)
    w = [math.exp((s - m) / t) for s in scores]
    total = sum(w)
    return [x / total for x in w]


def draw_proposals(scores: dict, root_of: dict, k: int = PROPOSAL_COUNT,
                   rng=random, t: Optional[float] = None) -> list:
    """k Ziehungen ohne Zuruecklegen; Softmax nach jeder Ziehung ueber die VERBLEIBENDEN Rezepte.
    Nach jeder Ziehung fliegen das Rezept und alle Varianten (gleicher root) raus."""
    pool = dict(scores)
    out = []
    while pool and len(out) < k:
        ids = list(pool)
        pick = rng.choices(ids, weights=softmax([pool[i] for i in ids], t))[0]
        out.append(pick)
        for i in [i for i in pool if root_of[i] == root_of[pick]]:
            del pool[i]
    return out


def swap_proposals(picks: list, candidates: list, root_of: dict, never_cooked: set,
                   wishlist: set, rng=random) -> list:
    """Jeder Vorschlag wird mit Wahrscheinlichkeit 1 - p getauscht (p^5 = SWAP_P5), ausser er
    steht auf der Wunschliste. Ersatz: erst nie gekochte, dann zufaellig aus dem Rest - nie
    ein Rezept oder eine Variante, die schon in der Liste steht."""
    p = SWAP_P5 ** (1 / PROPOSAL_COUNT)
    out = list(picks)
    for idx, pick in enumerate(out):
        if pick in wishlist or rng.random() < p:
            continue
        used = {root_of[i] for i in out}
        free = [c for c in candidates if root_of[c] not in used]
        fresh = [c for c in free if c in never_cooked]
        if fresh or free:
            out[idx] = rng.choice(fresh or free)
    return out


# ================= Pipeline =================
def build_propose_dataset(data: dict, user_id=None, today: Optional[date] = None) -> dict:
    """Pro Rezept: recipe, history, ingredients und alle Teil-Scores (I.2 - I.5 im Doc)."""
    today = today or date.today()
    recipes = data.get("recipes", [])

    history_by_recipe: dict = defaultdict(list)
    for h in data.get("history", []):
        history_by_recipe[h.get("recipe_id")].append(h)

    ingredients_by_recipe: dict = defaultdict(list)
    for ri in data.get("recipe_ingredients", []):
        ingredients_by_recipe[ri.get("recipe_id")].append(ri)

    by_id = {r.get("recipe_id"): r for r in recipes}
    ls_ids = last_supper(data, today)
    ls = merge_last_supper([recipe_features(by_id[i], data) for i in ls_ids if i in by_id])
    season_now = current_season(today)

    dataset = {}
    for r in recipes:
        rid = r.get("recipe_id")
        entry = history_by_recipe[rid][0] if history_by_recipe.get(rid) else None   # genau ein Eintrag pro Rezept
        d_score, remove = date_score(entry, today)
        mult, off, rules = calc_damping(recipe_features(r, data), ls, season_now)
        wish = user_id is not None and rl.is_wishlisted(data, rid, user_id)
        r_score = reward_score(r, entry)
        dataset[rid] = {
            "recipe": r,
            "history": history_by_recipe.get(rid, []),
            "ingredients": ingredients_by_recipe.get(rid, []),
            "never_cooked": not (entry or {}).get("last_date"),
            "date_score": d_score,
            "remove": remove,
            "reward_score": r_score,
            "damp_score_mult": mult,
            "damp_score_offset": off,
            "damp_rules": rules,
            "wishlist": wish,
            "score": calc_total_score(d_score, r_score, mult, off, wish),
        }
    return dataset


def hard_filter(dataset: dict, last_supper_ids: list, meal_type: str = "main_dish",
                diet: str = "any", blacklist: Optional[set] = None) -> list:
    """II.4 - recipe_ids, die nach allen harten Filtern uebrig bleiben.
    Allergien: noch nicht moeglich (lactose_free / gluten_free fehlen in den Daten)."""
    blacklist = blacklist or set()
    ls_roots = {variant_root(dataset[i]["recipe"]) for i in last_supper_ids if i in dataset}
    allowed = {r.get("recipe_id") for r in
               filter_recipes([d["recipe"] for d in dataset.values()], meal_type=meal_type, diet=diet)}
    return [
        rid for rid, d in dataset.items()
        if rid in allowed
        and not d["remove"]
        and variant_root(d["recipe"]) not in ls_roots
        and rid not in blacklist
        and not is_same_day(d["recipe"])
    ]


def propose(data: dict, user_id=None, today: Optional[date] = None, meal_type: str = "main_dish",
            diet: str = "any", blacklist: Optional[set] = None, rng=random) -> list[dict]:
    """Ganze Vorschlags-Pipeline (I.1 - I.6 im Doc). Gibt die vorgeschlagenen Rezept-Dicts zurueck.
    Wird vom Server noch NICHT benutzt."""
    today = today or date.today()
    dataset = build_propose_dataset(data, user_id, today)
    candidates = hard_filter(dataset, last_supper(data, today), meal_type, diet, blacklist)
    if not candidates:
        return []
    root_of = {rid: variant_root(dataset[rid]["recipe"]) for rid in candidates}
    picks = draw_proposals({rid: dataset[rid]["score"] for rid in candidates}, root_of, rng=rng)
    picks = swap_proposals(
        picks, candidates, root_of,
        never_cooked={rid for rid in candidates if dataset[rid]["never_cooked"]},
        wishlist={rid for rid in candidates if dataset[rid]["wishlist"]},
        rng=rng,
    )
    return [dataset[rid]["recipe"] for rid in picks]


# ================= Frontend / bestehende Filter =================
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
