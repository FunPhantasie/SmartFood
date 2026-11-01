from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional
import math
import random
import statistics

from Tools import RatingLogic as rl
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
WISHLIST_SCORE = 10       # Bonus fuer Rezepte auf der Wunschliste
WISHLIST_UNDAMPED = 5     # wishlist_score / WISHLIST_UNDAMPED kommt NACH der Daempfung dazu
SOFTMAX_T = 4             # Softmax-Temperatur: klein = die Besten gewinnen fast immer, gross = zufaelliger
SOFTMAX_T_RANGE = (1, 10) # vom User einstellbar (Reroll erhoeht T um 1)
SWAP_P5 = 0.8             # P(kein Tausch bei 5 Vorschlaegen)
PROPOSAL_COUNT = 5        # Anzahl Vorschlaege


def _mean(values) -> Optional[float]:
    values = [v for v in values or [] if v is not None]
    return sum(values) / len(values) if values else None


def rating(entry: Optional[dict], key: str, defaults: Optional[dict] = None) -> float:
    """Mittel der history-Bewertungen; ohne -> Vorab-Bewertung (default_ratings.yaml); ohne -> NEUTRAL_RATING."""
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
    defaults: Vorab-Bewertung des Rezepts (YamlEditor.default_rating) fuer fehlende repeat_ratings."""
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
    """reward mit Zwischenwerten. Fehlende Bewertungen -> Vorab-Bewertung (defaults), sonst NEUTRAL_RATING.
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
        "season": recipe.get("season") or "all",
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
def calc_total_score(date_s: float, reward_s: float, mult: float, off: float, wishlist: bool) -> float:
    """(date + reward + wishlist) · mult + offset + wishlist / WISHLIST_UNDAMPED"""
    w = WISHLIST_SCORE if wishlist else 0
    return (date_s + reward_s + w) * mult + off + w / WISHLIST_UNDAMPED


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
                   wishlist: set, rng=random, t: Optional[float] = None, swapped: Optional[dict] = None) -> list:
    """Jeder Vorschlag wird mit Wahrscheinlichkeit 1 - p getauscht (p^5 = SWAP_P5), ausser er
    steht auf der Wunschliste. Ersatz per Softmax: erst aus den nie gekochten Rezepten, dann aus
    dem Rest - nie ein Rezept oder eine Variante, die schon in der Liste steht. Nichts frei -> kein Tausch.
    swapped (optional): wird mit {Index: ("new" | "main", ersetzte recipe_id)} gefuellt."""
    p = SWAP_P5 ** (1 / PROPOSAL_COUNT)
    out = list(picks)
    for idx, pick in enumerate(out):
        if pick in wishlist or rng.random() < p:
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


def split_pools(dataset: dict, candidates: list) -> tuple[dict, dict]:
    """Teilt die erlaubten Rezepte in den Haupt-Pool (gekocht, vorab bewertet oder auf der Wunschliste)
    und den Pool der neuen, nie gekochten Rezepte. Rezepte ohne berechenbaren Score (nie gekocht, keine
    Zeiten) bekommen den Median aller berechneten Scores der Kandidaten.
    Rueckgabe: ({recipe_id: score} Haupt-Pool, {recipe_id: score} neue Rezepte)."""
    computed = [dataset[i]["score"] for i in candidates if dataset[i]["score"] is not None]
    median = statistics.median(computed) if computed else calc_total_score(
        NEVER_COOKED_DATE, calc_reward(NEUTRAL_RATING, NEUTRAL_RATING, MISSING_TIME), 1, 0, False)
    main, new = {}, {}
    for i in candidates:
        d = dataset[i]
        score = d["score"] if d["score"] is not None else median
        (new if d["never_cooked"] and not d["wishlist"] and not d.get("rated_ahead") else main)[i] = score
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
        wish = user_id is not None and rl.is_wishlisted(data, rid, user_id)
        score = None if rw["reward_score"] is None else calc_total_score(
            d["date_score"], rw["reward_score"], mult, off, wish)
        dataset[rid] = {
            "recipe": r,
            "history": history_by_recipe.get(rid, []),
            "ingredients": ingredients_by_recipe.get(rid, []),
            "ingredient_info": [ingredient_by_id[ri.get("ingredient_id")] for ri in ingredients_by_recipe.get(rid, [])
                                if ri.get("ingredient_id") in ingredient_by_id],
            "never_cooked": not (entry or {}).get("last_date"),
            "rated_ahead": any(v is not None for v in defaults.values()),   # Vorab-Bewertung -> bekannt
            "date": d,
            "reward": rw,
            "date_score": d["date_score"],
            "remove": d["remove"],
            "reward_score": rw["reward_score"],
            "damp_score_mult": mult,
            "damp_score_offset": off,
            "damp_rules": rules,
            "wishlist": wish,
            "score": score,          # None -> Median, siehe split_pools
        }
    return dataset


def hard_filter(dataset: dict, last_supper_ids: list, meal_type: str = "main_dish",
                diet: str = "any", blacklist: Optional[set] = None,
                include=(), exclude=(), allergies=()) -> list:
    """I.4 - recipe_ids, die nach allen harten Filtern uebrig bleiben. Die Wunschliste
    ueberstimmt remove aus date_score, die Blacklist gewinnt immer."""
    blacklist = blacklist or set()
    ls_roots = {variant_root(dataset[i]["recipe"]) for i in last_supper_ids if i in dataset}
    allowed = {r.get("recipe_id") for r in
               filter_recipes([d["recipe"] for d in dataset.values()], meal_type=meal_type, diet=diet)}
    return [
        rid for rid, d in dataset.items()
        if rid in allowed
        and (not d["remove"] or d["wishlist"])
        and variant_root(d["recipe"]) not in ls_roots
        and rid not in blacklist
        and not is_same_day(d["recipe"])
        and ingredient_ok(d["ingredient_info"], include, exclude, allergies)
    ]


# Herkunft eines Vorschlags (propose_detailed -> Abzeichen auf der Karte)
SOURCE_CYCLE = "cycle"          # normal aus dem Haupt-Pool gezogen (gekocht / vorab bewertet / Wunschliste)
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
    """Wie propose(), pro Vorschlag aber {recipe, source (SOURCE_*), score, wishlist, replaced}.
    replaced = recipe_id, die beim Tauschen ersetzt wurde (sonst None).
    pool="all": aus dem Haupt-Pool ziehen, zu wenige -> mit neuen Rezepten auffuellen, dann tauschen.
    pool="new": nur aus den nie gekochten Rezepten ziehen ('Neue Rezepte'-Button).
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
    main_pool, new_pool = split_pools(dataset, candidates)
    detail = lambda rid, source, replaced=None: {
        "recipe": dataset[rid]["recipe"], "source": source, "score": {**main_pool, **new_pool}[rid],
        "wishlist": dataset[rid]["wishlist"], "replaced": replaced}
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
    picks = swap_proposals(picks, new_pool, main_pool, root_of,
                           wishlist={rid for rid in candidates if dataset[rid]["wishlist"]}, rng=rng, t=t,
                           swapped=swapped)
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


def filter_recipes(recipes: list[dict], meal_type: str = "main_dish", diet: str = "any") -> list[dict]:
    """Typ-/Diaet-Filter (Teil von hard_filter). Zutaten-Filter (include/exclude/Allergien)
    brauchen die Zutaten und laufen deshalb in hard_filter ueber ingredient_ok.
    Rueckgabe: rohe Rezept-Dicts (fuers Frontend danach recipe_to_frontend())."""
    return [r for r in recipes if r.get("recipe_type") == meal_type and diet_ok(r.get("veg_type"), diet)]
