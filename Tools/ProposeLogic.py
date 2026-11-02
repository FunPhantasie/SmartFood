from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional
import math
import random
import statistics

from Tools import YamlEditor as yr

# Ueberblick:                    docs/ProposeLogic.md
# Formeln + Herleitung + Plots:  docs/Testing/*.ipynb (date_score, reward_score, damping, total_score)
# Logik-Test / Szenarien:        tests/test_propose_plan.py
# Echte Daten Schritt fuer Schritt: docs/Testing/test_with_data.ipynb
#
# Aufbau: pro Score eine reine Formel (calc_*, nur Zahlen rein/raus - so testbar) und eine
# Funktion, die die Eingaben aus den echten Daten (history-Eintrag, Rezept) holt.
# Die Formeln hier muessen 1:1 zu den Notebooks passen - aendern immer an beiden Stellen.

# ---------------- Stellschrauben ----------------
MAX_SCORE = 10
NEUTRAL_RATING = 5        # Mittelwert der 0-10 Skalen, gilt fuer jede fehlende Bewertung

# II.1 date_score (date_score.ipynb)
ZERO_CROSSING = 5         # b: Abstand (Tage), ab dem der Score positiv wird -> darunter remove
BASE_LEVEL = 0.8          # ohne Amplification erreicht die Kurve 80 % bei periodcycle_app
USAGE_WINDOW = 30         # Tage, ueber die die App-Nutzung gezaehlt wird
EMPTY_USAGE_DAYS = 3      # COUNT_USAGE_APP, wenn im USAGE_WINDOW gar nicht gekocht wurde
MIN_ROTATION_RECIPES = 5  # max(5, COUNT_RECIPES_COOKED_ATLEAST_TWICE)
MIN_PERIODCYCLE = 7       # max(7, periodcycle_app) - sonst kippt tau bei neuen Usern ins Negative
MAX_VAR_DAYS = 30         # var_days_app = min(30, Rezepte in Rotation)
REPEAT_STEEPNESS = 0.3    # k der Wdh-Verschiebung
MAX_REWARD = 0.9          # Wdh 10 holt ein Rezept hoechstens (1 - 0.9) = 10 % frueher
VAR_SCORE = 8             # Breite der usage_score-Glocke um Wdh 5
MIN_AMP, MAX_AMP = 0.1, 10
TAU_AMP = 2               # Tage, Breite des Amplification-Uebergangs um T
MIN_DATES_FOR_TARGET = 3  # <= 2 dates -> keine Abstands-Statistik, amp = 1
NEVER_COOKED_DATE = 5     # date_score fuer nie gekochte Rezepte

# II.2 reward_score (reward_score.ipynb)
COOK_MID = 50             # timescore = 0.5 bei so vielen Minuten
COOK_UNIT = 7.5           # Steilheit von timescore
TASTE_EXP = 1.8           # >1 -> schlechter Geschmack wird haerter bestraft
EFFORT_EXP = 2.4
EFFORT_WEIGHT = 0.5       # max. Verlust durch Aufwand (bei taste 10 und effort 10)
EFFORT_TASTE_EXP = 0.4    # Aufwand zaehlt mehr bei leckeren Gerichten
MISSING_TIME = 45         # Gesamtzeit eines gekochten Rezepts ohne hinterlegte Zeiten

# II.3 damping (damping.ipynb)
LAST_SUPPER_SIZE = 3      # die letzten n gekochten Gerichte ...
LAST_SUPPER_DAYS = 4      # ... sofern hoechstens so viele Tage her
DAMP_SPECS = {"sweet", "soup", "casserole"}   # nur diese Specs daempfen

# I.4 hard filter
SAME_DAY_LIMIT = 60       # prep oder cook > so viele Minuten -> raus (genau 60 ist noch ok)

# III total score / ziehen / tauschen (total_score.ipynb)
SOFTMAX_T = 4             # Softmax-Temperatur: klein = die Besten gewinnen fast immer, gross = zufaelliger
SOFTMAX_T_RANGE = (1, 10) # vom User einstellbar (Reroll erhoeht T um 1)
SWAP_P5 = 0.8             # P(kein Tausch bei 5 Vorschlaegen)
PROPOSAL_COUNT = 5        # Anzahl Vorschlaege
STARTER_COOKED_LIMIT = 10 # Startphase: hoechstens so viele verschiedene Rezepte gekocht -> alles ist Haupt-Pool


def _mean(values) -> Optional[float]:
    values = [v for v in values or [] if v is not None]
    return sum(values) / len(values) if values else None


def rating(entry: Optional[dict], key: str, defaults: Optional[dict] = None) -> float:
    """Mittel der history-Bewertungen; ohne -> Default-Bewertung (default_ratings.yaml); ohne -> NEUTRAL_RATING."""
    value = _mean((entry or {}).get(key))
    if value is None:
        value = (defaults or {}).get(key)
    return NEUTRAL_RATING if value is None else value


def _logistic(x: float) -> float:
    """1 / (1 + e^x) ohne Overflow bei sehr grossen x (Rezepte, die ueber Tage gehen)."""
    if x > 0:
        e = math.exp(-x)
        return e / (1 + e)
    return 1 / (1 + math.exp(x))


# ================= II.1 date_score =================
def app_stats(data: dict, today: Optional[date] = None) -> dict:
    """Rotationspunkt der App aus der history: COUNT_USAGE_APP = verschiedene Koch-Tage (alle
    Rezepte) im USAGE_WINDOW, COUNT_RECIPES_COOKED_ATLEAST_TWICE = Rezepte mit >= 2 dates.
    Mit den Untergrenzen fuer neue User (siehe Edge Cases in date_score.ipynb)."""
    today = today or date.today()
    since = today - timedelta(days=USAGE_WINDOW)
    cook_days, twice = set(), 0
    for h in data.get("history", []):
        dates = {date.fromisoformat(d) for d in h.get("dates") or []}
        cook_days |= {d for d in dates if since < d <= today}
        twice += len(dates) >= 2
    usage = len(cook_days) or EMPTY_USAGE_DAYS
    rotation = max(MIN_ROTATION_RECIPES, twice)
    periodcycle = max(MIN_PERIODCYCLE, USAGE_WINDOW / usage * rotation)
    return {
        "count_usage_app": usage,
        "count_recipes_twice": rotation,
        "average_usage": USAGE_WINDOW / usage,
        "periodcycle_app": periodcycle,
        "var_days_app": min(MAX_VAR_DAYS, rotation),
        "tau": (periodcycle - ZERO_CROSSING) / math.atanh(BASE_LEVEL),
    }


def gauss_cdf(x: float, mu: float, var: float) -> float:
    return 0.5 * (1 + math.erf((x - mu) / math.sqrt(2 * var)))


def repeat_shift(repeat: float, mean: float) -> float:
    """I) Wdh-Verschiebung in Tagen: 0 bei Wdh 5, Wdh 0 -> +34.8 % von mean, Wdh 10 -> -7.8 %."""
    return mean * (1 - MAX_REWARD) * (math.exp(-REPEAT_STEEPNESS * (repeat - NEUTRAL_RATING)) - 1)


def usage_score(repeat: float) -> float:
    """Gewicht der Korrektur: 1 bei Wdh 5, ~0.21 bei Wdh 0 / 10 (nicht normierte Glocke)."""
    return math.exp(-0.5 * (repeat - NEUTRAL_RATING) ** 2 / VAR_SCORE)


def correction_days(mean: float, std: float, repeat: float, app: dict) -> float:
    """II) Zug Richtung periodcycle_app + I) Wdh-Verschiebung. T = mean + correction_days(...)."""
    m, var = app["periodcycle_app"], app["var_days_app"]
    p_akt = gauss_cdf(mean + std, m, var) - gauss_cdf(mean - std, m, var)
    p_best = gauss_cdf(m + std, m, var) - gauss_cdf(m - std, m, var)
    correction = (m - mean) * (p_best - p_akt) * usage_score(repeat)
    return correction + repeat_shift(repeat, mean)


def amplification(dist_last: float, target: float) -> float:
    """MIN_AMP weit vor T, (MIN_AMP + MAX_AMP) / 2 genau bei T, MAX_AMP weit nach T."""
    t = math.tanh((dist_last - target) / TAU_AMP)
    return MIN_AMP + (MAX_AMP - MIN_AMP) * (t + 1) / 2


def calc_date_score(amp: float, dist_last: float, tau: float) -> float:
    """Rohwert der Basiskurve - <= 0 heisst remove (date_score wird dann 0)."""
    return MAX_SCORE * math.tanh(amp / tau * (dist_last - ZERO_CROSSING))


def date_details(entry: Optional[dict], app: dict, today: Optional[date] = None,
                 defaults: Optional[dict] = None) -> dict:
    """date_score fuer EINEN history-Eintrag mit allen Zwischenwerten (fuer test_with_data).
    defaults: Default-Bewertung des Rezepts (YamlEditor.default_rating) fuer fehlende repeat_ratings."""
    today = today or date.today()
    entry = entry or {}
    out = {"dist_last": None, "n_dates": 0, "mean": None, "std": None, "repeat": None,
           "target": None, "amp": None, "date_score": NEVER_COOKED_DATE, "remove": False}
    if not entry.get("last_date"):                      # nie gekocht
        return out

    dates = sorted({date.fromisoformat(d) for d in entry.get("dates") or []})
    dist_last = (today - date.fromisoformat(entry["last_date"])).days
    repeat = rating(entry, "repeat_rating", defaults)
    out.update(dist_last=dist_last, n_dates=len(dates), repeat=repeat, amp=1.0)

    if len(dates) >= MIN_DATES_FOR_TARGET:
        gaps = [(b - a).days for a, b in zip(dates[:-1], dates[1:])]
        mean, std = statistics.fmean(gaps), statistics.pstdev(gaps)
        target = mean + correction_days(mean, std, repeat, app)
        out.update(mean=mean, std=std, target=target, amp=amplification(dist_last, target))

    raw = calc_date_score(out["amp"], dist_last, app["tau"])
    out.update(date_score=max(0.0, raw), remove=raw <= 0)
    return out


def date_score(entry: Optional[dict], app: dict, today: Optional[date] = None,
               defaults: Optional[dict] = None) -> tuple[float, bool]:
    d = date_details(entry, app, today, defaults)
    return d["date_score"], d["remove"]


# ================= II.2 reward_score =================
def timescore(minutes: float) -> float:
    return _logistic((minutes - COOK_MID) / COOK_UNIT)


def calc_reward(taste: float, effort: float, minutes: float) -> float:
    """Reine Formel. taste 0-10, effort 0-10 (10 = hoher Aufwand). Ergebnis 0 - 10."""
    taste_part = (taste / 10) ** TASTE_EXP                                   # schlechter Geschmack hart bestraft
    cost = (effort / 10) ** EFFORT_EXP
    effort_part = 1 - EFFORT_WEIGHT * (taste / 10) ** EFFORT_TASTE_EXP * cost  # Aufwand zaehlt mehr bei leckeren Gerichten
    return 10 * timescore(max(0, minutes)) * taste_part * effort_part


def recipe_minutes(recipe: dict) -> Optional[float]:
    """prep + cook; None, wenn beide Zeiten fehlen."""
    prep, cook = recipe.get("prep_minutes"), recipe.get("cook_minutes")
    if prep is None and cook is None:
        return None
    return (prep or 0) + (cook or 0)


def reward_details(recipe: dict, entry: Optional[dict], defaults: Optional[dict] = None) -> dict:
    """reward mit Zwischenwerten. Fehlende Bewertungen -> Default-Bewertung (defaults), sonst NEUTRAL_RATING.
    Nie gekochtes Rezept ohne Zeiten -> reward None (bekommt spaeter den Median-Score, siehe split_pools)."""
    entry = entry or {}
    taste, effort = rating(entry, "taste_rating", defaults), rating(entry, "effort_rating", defaults)
    minutes = recipe_minutes(recipe)
    if minutes is None and entry.get("last_date"):
        minutes = MISSING_TIME
    reward = None if minutes is None else calc_reward(taste, effort, minutes)
    return {"taste": taste, "effort": effort, "minutes": minutes, "reward_score": reward}


def reward_score(recipe: dict, entry: Optional[dict], defaults: Optional[dict] = None) -> Optional[float]:
    return reward_details(recipe, entry, defaults)["reward_score"]


# ================= II.3 damp_score =================
def current_season(today: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(today.month, "autumn")


def recipe_features(recipe: dict, data: dict) -> dict:
    """Alles, was die Daempfung von einem Rezept braucht. Einzige Stelle, die die Datenfelder
    kennt - fehlende Felder (origin, cooking_method, recipe_spec, main_ingredient, side_dish) ergeben
    einfach leere Werte, die Regel greift dann nicht.
    main_ingredient (eine ID oder eine Liste) und side_dish sind Rezeptfelder (beim Erstellen bestaetigt,
    None = keine): Zutaten aus ingredients.yaml, die in der Zutatenliste des Rezepts stehen muessen - sonst
    ValueError (Datenfehler, siehe YamlEditor.data_problems). Ohne Hauptzutat / Beilage wird darueber nicht gedaempft.
    meats = Rezeptfeld meat_types (Fleischsorten, beim Bearbeiten aus den Zutaten befuellt); fehlt das
    Feld, wird es aus den meat_type der Zutaten abgeleitet."""
    ingredients = {i.get("ingredient_id"): i for i in data.get("ingredients", [])}
    rid = recipe.get("recipe_id")
    ids = [ri.get("ingredient_id") for ri in data.get("recipe_ingredients", [])
           if ri.get("recipe_id") == rid]
    origin = recipe.get("origin") or []
    side = recipe.get("side_dish")
    side = None if side == yr.NOT_SPECIFIC else side
    mains = yr.main_ingredients(recipe.get("main_ingredient"))
    for field, value in [("main_ingredient", m) for m in mains] + ([("side_dish", side)] if side is not None else []):
        if value not in ingredients:
            raise ValueError(f"recipe {rid}: {field} {value!r} is not in ingredients.yaml")
        if value not in ids:
            raise ValueError(f"recipe {rid}: {field} {value!r} is not in its ingredient list")
    meats = recipe.get("meat_types")
    specs = {recipe.get("recipe_spec")} & DAMP_SPECS
    if recipe.get("sweet"):
        specs.add("sweet")
    return {
        "season": yr.season_parts(recipe.get("season"))[0] or "all",   # only_summer -> summer (Bonus wie summer)
        "origins": set(origin if isinstance(origin, list) else [origin]),
        "method": recipe.get("cooking_method"),
        "specs": specs,
        "sides": {side} if side is not None else set(),
        "mains": set(mains),
        "mains_meat_or_side": {m for m in mains if ingredients[m].get("veg_type") in ("meat", "fish")
                               or ingredients[m].get("side_dish")},
        "meats": set(meats if meats is not None else yr.meat_types_of(data, ids)),
    }


def merge_last_supper(features: list[dict]) -> dict:
    """EINE zusammengefuehrte Liste aus allen last_supper-Gerichten (einmal, vor der Schleife).
    meats ist eine Liste: dieselbe Fleischsorte in zwei Gerichten zaehlt fuer len() doppelt."""
    return {
        "origins": set().union(*(f["origins"] for f in features)),
        "methods": {f["method"] for f in features if f["method"]},
        "specs": set().union(*(f["specs"] for f in features)),
        "sides": set().union(*(f["sides"] for f in features)),
        "mains": set().union(*(f["mains"] for f in features)),
        "meats": [m for f in features for m in sorted(f["meats"], key=str)],
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
        f = max(0.0, 1 - 0.1 * len(ls["meats"]))
        mult *= f; log.append(f"meat x{f:.1f}")
    if cand["meats"] & set(ls["meats"]):
        off -= 3; log.append("same meat -3")
    same_mains = cand["mains"] & ls["mains"]      # mehrere Hauptzutaten: Regel trotzdem nur einmal
    if same_mains:
        if same_mains & cand["mains_meat_or_side"]:
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


# ================= I.4 hard filter =================
def variant_root(recipe: dict) -> int:
    """Original-Rezept einer Variante (oder das Rezept selbst) - Varianten teilen den root."""
    return recipe.get("variant_of") or recipe.get("recipe_id")


def is_same_day(recipe: dict) -> bool:
    return any((recipe.get(k) or 0) > SAME_DAY_LIMIT for k in ("prep_minutes", "cook_minutes"))


def user_blacklist(data: dict, user_id) -> set:
    """recipe_ids, die der User gar nicht mag (blacklist.yaml, gleicher Aufbau wie wishlist.yaml)."""
    if user_id is None:
        return set()
    return {b.get("recipe_id") for b in data.get("blacklist", []) if str(b.get("user_id")) == str(user_id)}


def _matches(ingredient: dict, wanted) -> bool:
    """include/exclude-Eintrag aus dem Frontend: Zutaten-ID oder Name (Gross/Klein egal)."""
    wanted = str(wanted).strip().lower()
    return wanted in (str(ingredient.get("ingredient_id")), str(ingredient.get("name") or "").strip().lower())


def ingredient_ok(ingredients: list[dict], include=(), exclude=(), allergies=()) -> bool:
    """include: ALLE muessen vorkommen, exclude: KEINE darf vorkommen.
    allergies z.B. ["lactose", "gluten"] -> raus, wenn eine Zutat lactose_free / gluten_free == False
    hat. Fehlt das Feld, ist es unbekannt und filtert (noch) nicht."""
    if not all(any(_matches(i, w) for i in ingredients) for w in include):
        return False
    if any(_matches(i, w) for i in ingredients for w in exclude):
        return False
    return not any(i.get(f"{a}_free") is False for i in ingredients for a in allergies)


# ================= III total score, draw, swap =================
def calc_total_score(date_s: float, reward_s: float, mult: float, off: float) -> float:
    """(date + reward) · mult + offset. Die Wunschliste hat keinen Einfluss (eigene Seite /wishlist)."""
    return (date_s + reward_s) * mult + off


def clamp_t(t: Optional[float]) -> float:
    lo, hi = SOFTMAX_T_RANGE
    return min(hi, max(lo, float(t if t is not None else SOFTMAX_T)))


def softmax(scores: list[float], t: Optional[float] = None) -> list[float]:
    """p_i = exp(s_i/T) / sum exp(s_j/T). max wird nur fuer numerische Sicherheit abgezogen."""
    t = t or SOFTMAX_T
    m = max(scores)
    w = [math.exp((s - m) / t) for s in scores]
    total = sum(w)
    return [x / total for x in w]


def draw_proposals(scores: dict, root_of: dict, k: int = PROPOSAL_COUNT,
                   rng=random, t: Optional[float] = None, used_roots: Optional[set] = None) -> list:
    """k Ziehungen ohne Zuruecklegen; Softmax nach jeder Ziehung ueber die VERBLEIBENDEN Rezepte.
    Nach jeder Ziehung fliegen das Rezept und alle Varianten (gleicher root) raus.
    used_roots: Familien, die schon in der Liste stehen (z.B. beim Auffuellen)."""
    used_roots = set(used_roots or ())
    pool = {i: s for i, s in scores.items() if root_of[i] not in used_roots}
    out = []
    while pool and len(out) < k:
        ids = list(pool)
        pick = rng.choices(ids, weights=softmax([pool[i] for i in ids], t))[0]
        out.append(pick)
        for i in [i for i in pool if root_of[i] == root_of[pick]]:
            del pool[i]
    return out


def swap_proposals(picks: list, new_pool: dict, main_pool: dict, root_of: dict,
                   rng=random, t: Optional[float] = None, swapped: Optional[dict] = None) -> list:
    """Jeder Vorschlag wird mit Wahrscheinlichkeit 1 - p getauscht (p^5 = SWAP_P5). Ersatz per Softmax: erst aus den nie gekochten Rezepten, dann aus
    dem Rest - nie ein Rezept oder eine Variante, die schon in der Liste steht. Nichts frei -> kein Tausch.
    swapped (optional): wird mit {Index: ("new" | "main", ersetzte recipe_id)} gefuellt."""
    p = SWAP_P5 ** (1 / PROPOSAL_COUNT)
    out = list(picks)
    for idx, pick in enumerate(out):
        if rng.random() < p:
            continue
        used = {root_of[i] for i in out}
        for pool in (new_pool, main_pool):
            repl = draw_proposals(pool, root_of, k=1, rng=rng, t=t, used_roots=used)
            if repl:
                out[idx] = repl[0]
                if swapped is not None:
                    swapped[idx] = ("new" if pool is new_pool else "main", pick)
                break
    return out


def cooked_count(data: dict) -> int:
    """Wie viele verschiedene Rezepte der User schon gekocht hat (history-Eintrag mit last_date)."""
    return sum(1 for h in data.get("history", []) if h.get("last_date"))


def is_starter_phase(data: dict) -> bool:
    """Startphase: hoechstens STARTER_COOKED_LIMIT verschiedene Rezepte gekocht -> es gibt (fuer die normale
    Ziehung) keinen Pool der neuen Rezepte, alle erlaubten Rezepte sind im Haupt-Pool."""
    return cooked_count(data) <= STARTER_COOKED_LIMIT


def split_pools(dataset: dict, candidates: list, starter: bool = False) -> tuple[dict, dict]:
    """Teilt die erlaubten Rezepte in den Haupt-Pool (gekocht oder default bewertet)
    und den Pool der neuen, nie gekochten Rezepte. starter=True (Startphase, is_starter_phase): alles
    in den Haupt-Pool. Rezepte ohne berechenbaren Score (nie gekocht, keine Zeiten) bekommen den Median
    aller berechneten Scores der Kandidaten.
    Rueckgabe: ({recipe_id: score} Haupt-Pool, {recipe_id: score} neue Rezepte)."""
    computed = [dataset[i]["score"] for i in candidates if dataset[i]["score"] is not None]
    median = statistics.median(computed) if computed else calc_total_score(
        NEVER_COOKED_DATE, calc_reward(NEUTRAL_RATING, NEUTRAL_RATING, MISSING_TIME), 1, 0)
    main, new = {}, {}
    for i in candidates:
        d = dataset[i]
        score = d["score"] if d["score"] is not None else median
        is_new = d["never_cooked"] and not d.get("rated_ahead")
        (new if is_new and not starter else main)[i] = score
    return main, new


# ================= Pipeline =================
def build_propose_dataset(data: dict, user_id=None, today: Optional[date] = None) -> dict:
    """Pro Rezept: recipe, history, ingredients und alle Teil-Scores mit Zwischenwerten (I.2 im Doc)."""
    today = today or date.today()
    recipes = data.get("recipes", [])

    history_by_recipe: dict = defaultdict(list)
    for h in data.get("history", []):
        history_by_recipe[h.get("recipe_id")].append(h)

    ingredients_by_recipe: dict = defaultdict(list)
    for ri in data.get("recipe_ingredients", []):
        ingredients_by_recipe[ri.get("recipe_id")].append(ri)

    ingredient_by_id = {i.get("ingredient_id"): i for i in data.get("ingredients", [])}
    by_id = {r.get("recipe_id"): r for r in recipes}
    app = app_stats(data, today)
    ls_ids = last_supper(data, today)
    ls = merge_last_supper([recipe_features(by_id[i], data) for i in ls_ids if i in by_id])
    season_now = current_season(today)

    dataset = {}
    for r in recipes:
        rid = r.get("recipe_id")
        entry = history_by_recipe[rid][0] if history_by_recipe.get(rid) else None   # genau ein Eintrag pro Rezept
        defaults = yr.default_rating(data, rid)
        d = date_details(entry, app, today, defaults)
        rw = reward_details(r, entry, defaults)
        mult, off, rules = calc_damping(recipe_features(r, data), ls, season_now)
        season, only_season = yr.season_parts(r.get("season"))
        score = None if rw["reward_score"] is None else calc_total_score(
            d["date_score"], rw["reward_score"], mult, off)
        dataset[rid] = {
            "recipe": r,
            "history": history_by_recipe.get(rid, []),
            "ingredients": ingredients_by_recipe.get(rid, []),
            "ingredient_info": [ingredient_by_id[ri.get("ingredient_id")] for ri in ingredients_by_recipe.get(rid, [])
                                if ri.get("ingredient_id") in ingredient_by_id],
            "never_cooked": not (entry or {}).get("last_date"),
            "rated_ahead": any(v is not None for v in defaults.values()),   # Default-Bewertung -> bekannt
            "out_of_season": only_season and season != season_now,           # only_<saison> -> harter Filter
            "date": d,
            "reward": rw,
            "date_score": d["date_score"],
            "remove": d["remove"],
            "reward_score": rw["reward_score"],
            "damp_score_mult": mult,
            "damp_score_offset": off,
            "damp_rules": rules,
            "score": score,          # None -> Median, siehe split_pools
        }
    return dataset


def hard_filter(dataset: dict, last_supper_ids: list, meal_type: str = "main_dish",
                diet: str = "any", blacklist: Optional[set] = None,
                include=(), exclude=(), allergies=()) -> list:
    """I.4 - recipe_ids, die nach allen harten Filtern uebrig bleiben."""
    reasons = exclusion_reasons(dataset, last_supper_ids, meal_type, diet, blacklist, include, exclude, allergies)
    return [rid for rid, r in reasons.items() if not r]


def exclusion_reasons(dataset: dict, last_supper_ids: list, meal_type: str = "main_dish",
                      diet: str = "any", blacklist: Optional[set] = None,
                      include=(), exclude=(), allergies=()) -> dict:
    """Pro recipe_id die harten Filter, an denen es scheitert (leer = erlaubt) - fuer hard_filter und die
    Score-Tabelle der Entwicklerseite."""
    blacklist = blacklist or set()
    ls_roots = {variant_root(dataset[i]["recipe"]) for i in last_supper_ids if i in dataset}
    out = {}
    for rid, d in dataset.items():
        r = d["recipe"]
        checks = [
            (r.get("recipe_type") != meal_type, f"Typ {r.get('recipe_type')} (gesucht: {meal_type})"),
            (not diet_ok(r.get("veg_type"), diet), f"Ernaehrung {r.get('veg_type')} (gesucht: {diet})"),
            (d.get("out_of_season", False), f"Saison: {r.get('season')}"),
            (d["remove"], f"vor {d['date']['dist_last']} Tagen gekocht"),
            (variant_root(d["recipe"]) in ls_roots, "letzte Mahlzeiten (Familie)"),
            (rid in blacklist, "Blacklist"),
            (is_same_day(d["recipe"]), f"ueber {SAME_DAY_LIMIT} min"),
            (not ingredient_ok(d["ingredient_info"], include, exclude, allergies), "Zutaten / Allergie"),
        ]
        out[rid] = [reason for failed, reason in checks if failed]
    return out


def ranking(data: dict, user_id=None, today: Optional[date] = None, meal_type: str = "main_dish",
            diet: str = "any", include=(), exclude=(), allergies=()) -> list[dict]:
    """Score-Tabelle ohne Ziehung (Entwicklerseite): pro Rezept Teil-Scores, Pool, total (wie beim Ziehen,
    fehlender Score = Median), Ausschlussgruende und Platz unter den erlaubten. Sortiert: erlaubte nach total,
    dann die ausgeschlossenen."""
    today = today or date.today()
    dataset = build_propose_dataset(data, user_id, today)
    reasons = exclusion_reasons(dataset, last_supper(data, today), meal_type, diet, user_blacklist(data, user_id),
                                include, exclude, allergies)
    candidates = [rid for rid, r in reasons.items() if not r]
    starter = is_starter_phase(data)
    main_pool, new_pool = split_pools(dataset, candidates, starter=starter)
    pooled = {**main_pool, **new_pool}       # Scores wie beim Ziehen (fehlender Score = Median der Kandidaten)
    rows = []
    for rid, d in dataset.items():
        known = starter or not d["never_cooked"] or d["rated_ahead"]
        total = pooled.get(rid, d["score"])   # ausgeschlossen ohne Score -> None
        rows.append({
            "recipe_id": rid, "name": d["recipe"].get("name"), "recipe_type": d["recipe"].get("recipe_type"),
            "season": d["recipe"].get("season") or "all",
            "pool": "main" if known else "new", "date_score": d["date_score"], "dist_last": d["date"]["dist_last"],
            "n_dates": d["date"]["n_dates"], "reward_score": d["reward_score"], "taste": d["reward"]["taste"],
            "effort": d["reward"]["effort"], "minutes": d["reward"]["minutes"], "damp_mult": d["damp_score_mult"],
            "damp_offset": d["damp_score_offset"], "damp_rules": d["damp_rules"],
            "rated_ahead": d["rated_ahead"], "total": total, "total_is_median": d["score"] is None and rid in pooled,
            "excluded": reasons[rid], "rank": None,
        })
    allowed_rows = sorted((r for r in rows if not r["excluded"]), key=lambda r: -r["total"])
    for i, r in enumerate(allowed_rows, 1):
        r["rank"] = i
    excluded = sorted((r for r in rows if r["excluded"]), key=lambda r: -(r["total"] if r["total"] is not None else -1e9))
    return allowed_rows + excluded


RANKING_TYPE_ORDER = ("main_dish", "side_dish", "sweet", "snack", "dip", "wuerzung")   # Gruppen auf /dev/scores


def ranking_by_type(data: dict, user_id=None, today: Optional[date] = None, allergies=()) -> list[dict]:
    """ranking() pro Gerichttyp (Entwicklerseite): je Gruppe nur die Rezepte DIESES Typs - erlaubte nach Platz,
    dann die, die dazugehoeren, aber gerade aus einem anderen Grund ausgeschlossen sind (60 min, Saison, ...).
    Reihenfolge RANKING_TYPE_ORDER, unbekannte Typen danach. Rueckgabe: [{meal_type, rows, main_pool, new_pool}]."""
    types = {r.get("recipe_type") for r in data.get("recipes", []) if r.get("recipe_type")}
    order = [t for t in RANKING_TYPE_ORDER if t in types] + sorted(types - set(RANKING_TYPE_ORDER))
    groups = []
    for meal_type in order:
        rows = [r for r in ranking(data, user_id, today, meal_type, allergies=allergies) if r["recipe_type"] == meal_type]
        allowed = [r for r in rows if not r["excluded"]]
        groups.append({"meal_type": meal_type, "rows": rows,
                       "main_pool": sum(r["pool"] == "main" for r in allowed),
                       "new_pool": sum(r["pool"] == "new" for r in allowed)})
    return groups


# Herkunft eines Vorschlags (propose_detailed -> Abzeichen auf der Karte)
SOURCE_CYCLE = "cycle"          # normal aus dem Haupt-Pool gezogen (gekocht / default bewertet; Startphase: alle)
SOURCE_FILL = "fill"            # Haupt-Pool zu klein -> mit einem neuen Rezept aufgefuellt
SOURCE_SWAP_NEW = "swap_new"    # beim Tauschen durch ein neues Rezept ersetzt
SOURCE_SWAP_MAIN = "swap_main"  # beim Tauschen ersetzt, kein neues frei -> aus dem Haupt-Pool
SOURCE_NEW_POOL = "new_pool"    # 'Neue Rezepte'-Button (pool="new")


def propose(data: dict, user_id=None, today: Optional[date] = None, meal_type: str = "main_dish",
            diet: str = "any", blacklist: Optional[set] = None, rng=random, k: int = PROPOSAL_COUNT,
            include=(), exclude=(), allergies=(), t: Optional[float] = None, pool: str = "all") -> list[dict]:
    """Ganze Vorschlags-Pipeline (I.1 - I.6 im Doc). Gibt bis zu k vorgeschlagene Rezept-Dicts zurueck."""
    return [p["recipe"] for p in propose_detailed(data, user_id, today, meal_type, diet, blacklist, rng, k,
                                                  include, exclude, allergies, t, pool)]


def propose_detailed(data: dict, user_id=None, today: Optional[date] = None, meal_type: str = "main_dish",
                     diet: str = "any", blacklist: Optional[set] = None, rng=random, k: int = PROPOSAL_COUNT,
                     include=(), exclude=(), allergies=(), t: Optional[float] = None, pool: str = "all") -> list[dict]:
    """Wie propose(), pro Vorschlag aber {recipe, source (SOURCE_*), score, replaced}.
    replaced = recipe_id, die beim Tauschen ersetzt wurde (sonst None).
    pool="all": aus dem Haupt-Pool ziehen, zu wenige -> mit neuen Rezepten auffuellen, dann tauschen.
    In der Startphase (is_starter_phase) ist alles Haupt-Pool - kein Auffuellen, Tauschen nur innerhalb.
    pool="new": nur aus den nie gekochten Rezepten ziehen ('Neue Rezepte'-Button, auch in der Startphase).
    blacklist kommt zusaetzlich zur blacklist.yaml des Users dazu."""
    today = today or date.today()
    t = clamp_t(t)
    dataset = build_propose_dataset(data, user_id, today)
    blacklist = set(blacklist or ()) | user_blacklist(data, user_id)
    candidates = hard_filter(dataset, last_supper(data, today), meal_type, diet, blacklist,
                             include, exclude, allergies)
    if not candidates:
        return []
    root_of = {rid: variant_root(dataset[rid]["recipe"]) for rid in candidates}
    # 'Neue Rezepte'-Button: immer die nie gekochten. Normale Ziehung in der Startphase: alles Haupt-Pool.
    main_pool, new_pool = split_pools(dataset, candidates, starter=pool != "new" and is_starter_phase(data))
    detail = lambda rid, source, replaced=None: {
        "recipe": dataset[rid]["recipe"], "source": source, "score": {**main_pool, **new_pool}[rid],
        "replaced": replaced}
    if pool == "new":
        return [detail(rid, SOURCE_NEW_POOL) for rid in draw_proposals(new_pool, root_of, k=k, rng=rng, t=t)]

    picks = draw_proposals(main_pool, root_of, k=k, rng=rng, t=t)
    sources = [SOURCE_CYCLE] * len(picks)
    if len(picks) < k:   # zu wenige -> mit neuen Rezepten auffuellen
        fill = draw_proposals(new_pool, root_of, k=k - len(picks), rng=rng, t=t,
                              used_roots={root_of[i] for i in picks})
        picks += fill
        sources += [SOURCE_FILL] * len(fill)
    swapped: dict = {}
    picks = swap_proposals(picks, new_pool, main_pool, root_of, rng=rng, t=t, swapped=swapped)
    return [detail(rid, {"new": SOURCE_SWAP_NEW, "main": SOURCE_SWAP_MAIN}[swapped[i][0]], swapped[i][1])
            if i in swapped else detail(rid, sources[i]) for i, rid in enumerate(picks)]


# ================= Frontend / bestehende Filter =================
def recipe_to_frontend(r: dict, is_new: bool = False) -> dict:
    """Convert recipe dict to frontend format. is_new = noch nie gekocht."""
    return {
        "id": r.get("recipe_id"),
        "name": r.get("name"),
        "recipe_type": r.get("recipe_type", "-"),
        "veg_type": r.get("veg_type"),
        "prep_t": r.get("prep_minutes", "0"),
        "cook_t": r.get("cook_minutes", "0"),
        "season": r.get("season", "always"),
        "is_new": is_new,
    }


def diet_ok(veg_type: Optional[str], diet: str) -> bool:
    """diet aus dem Frontend: any, vegan, vegetarian (vegan zaehlt mit), nonvegan, meat."""
    if diet == "any":
        return True
    if diet == "vegetarian":
        return veg_type in ("vegan", "vegetarian")
    if diet == "nonvegan":
        return veg_type != "vegan"
    return veg_type == diet
