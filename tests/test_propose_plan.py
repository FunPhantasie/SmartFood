"""Example scenarios for the propose logic in Tools/ProposeLogic.py (docs/ProposeLogic.md).

Run from the project root (the server does NOT need to run):
       python tests/test_propose_plan.py      (prints all tables + sanity checks)
  or:  python -m pytest tests/test_propose_plan.py

Formulas: derived + plotted in docs/Testing/*.ipynb, implemented in Tools/ProposeLogic.py.
This file only builds example data (history entries, recipes, ...) and checks the results.
Scales: taste, repeat (Wdh) and effort all 0-10 (5 = neutral, effort 10 = high effort).
"""
from __future__ import annotations
import math
import random
import sys
import tempfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))   # project root -> "Tools" importable
from Tools import ProposeLogic as pl  # noqa: E402
from Tools import RatingLogic as rl  # noqa: E402
from Tools import YamlEditor as yr  # noqa: E402

TODAY = date(2026, 9, 28)   # fixed, so every run gives the same numbers (autumn)


# ================= scenario builders =================
def entry(repeat=None, every=None, last_ago=None, count=3):
    """History entry like in history.yaml: cooked `count` times, every `every` days,
    last time `last_ago` days ago. last_ago=None -> never cooked."""
    if last_ago is None:
        return {"repeat_rating": [repeat]} if repeat is not None else {}
    last = TODAY - timedelta(days=last_ago)
    n = count if every else 1
    dates = sorted((last - timedelta(days=i * (every or 0))).isoformat() for i in range(n))
    return {"last_date": last.isoformat(), "dates": dates,
            "repeat_rating": [repeat] * n if repeat is not None else []}


def F(season="all", origin=(), spec=None, sweet=False, side=None, meat=None, main=None, main_meat_or_side=False):
    """Damping features of one recipe (same shape as pl.recipe_features)."""
    specs = ({spec} & pl.DAMP_SPECS) | ({"sweet"} if sweet else set())
    return {"season": season, "origins": set(origin), "method": None, "specs": specs,
            "sides": {side} if side else set(), "main": main, "main_meat_or_side": main_meat_or_side,
            "meats": {meat} if meat else set()}


# rotation point of the example below: 20 recipes cooked >= twice, cooked every 3 days -> 60 days
APP = {"count_usage_app": 10, "count_recipes_twice": 20, "average_usage": 3.0, "periodcycle_app": 60.0,
       "var_days_app": 20, "tau": (60.0 - pl.ZERO_CROSSING) / math.atanh(pl.BASE_LEVEL)}

DATE_CASES = [   # name, repeat, every, last_ago, count
    ("never cooked", None, None, None, 0),
    ("cooked today, once", 5, None, 0, 1),
    ("once, 7 days ago", 5, None, 7, 1),
    ("twice, 14 apart, last 14 ago (amp 1)", 5, 14, 14, 2),
    ("every 7 days, last 3 ago", 5, 7, 3, 4),
    ("every 7 days, last 7 ago", 5, 7, 7, 4),
    ("every 7 days, last 14 ago", 5, 7, 14, 4),
    ("every 30 days, last 20 ago, Wdh 2", 2, 30, 20, 4),
    ("every 30 days, last 20 ago, Wdh 5", 5, 30, 20, 4),
    ("every 30 days, last 20 ago, Wdh 9", 9, 30, 20, 4),
    ("every 30 days, last 40 ago, Wdh 5", 5, 30, 40, 4),
    ("every 90 days, last 90 ago, Wdh 5", 5, 90, 90, 4),
]

LAST_SUPPER = [
    F(origin=["indian"], side="rice", meat="chicken", main="chicken", main_meat_or_side=True),   # chicken curry
    F(season="autumn", spec="soup", main="pumpkin"),                                             # pumpkin soup
    F(origin=["asian"], side="rice", meat="chicken", main="chicken", main_meat_or_side=True),    # chicken wok
]
LS = pl.merge_last_supper(LAST_SUPPER)
DAMP_CASES = {
    "Butter chicken": F(origin=["indian"], side="rice", meat="chicken", main="chicken", main_meat_or_side=True),
    "Tomato soup": F(spec="soup", main="tomato"),
    "Veggie pasta": F(origin=["italian"], side="noodles", main="vegetables"),
    "Summer salad": F(season="summer", spec="salad"),
    "Beef burger": F(origin=["american"], meat="beef", main="beef", main_meat_or_side=True),
    "Pumpkin curry": F(origin=["indian"], side="rice", main="pumpkin"),
    "Rice bowl": F(origin=["asian"], side="rice", main="rice", main_meat_or_side=True),
}

DRAW_SCORES = {"A (20)": 20, "A-rice variant (20)": 20, "B (10)": 10, "G (8)": 8, "C (5)": 5,
               "D (2)": 2, "E (0.5)": 0.5, "F (-4)": -4}
DRAW_ROOTS = {n: n for n in DRAW_SCORES} | {"A-rice variant (20)": "A (20)"}


def example_data():
    """Small fake database in the shape of server_data/*.yaml (+ planned fields from doc V)."""
    ing = [(1, "Rice", True, "vegan", "ingredient"), (2, "Noodles", True, "vegan", "ingredient"),
           (3, "Chicken", False, "meat", "ingredient"), (4, "Beef", False, "meat", "ingredient"),
           (5, "Pumpkin", False, "vegan", "ingredient"), (6, "Tomato", False, "vegan", "ingredient"),
           (7, "Water", False, "vegan", "basic"), (8, "Salt", False, "vegan", "spice")]
    recipes = [   # id, name, type, veg, origin, spec, main, prep, cook, variant_of, ingredients
        (1, "Chicken curry", "main_dish", "meat", ["indian"], None, 3, 15, 25, None, [1, 3]),
        (2, "Pumpkin soup", "main_dish", "vegan", [], "soup", 5, 15, 20, None, [5]),
        (3, "Chicken curry (noodles)", "main_dish", "meat", ["indian"], None, 3, 15, 25, 1, [2, 3]),
        (4, "Butter chicken", "main_dish", "meat", ["indian"], None, 3, 15, 30, None, [1, 3]),
        (5, "Veggie pasta", "main_dish", "vegan", ["italian"], None, 2, 10, 15, None, [2, 6]),
        (6, "Beef burger", "main_dish", "meat", ["american"], None, 4, 15, 15, None, [4]),
        (7, "Tomato soup", "main_dish", "vegan", [], "soup", 6, 10, 20, None, [6, 7, 8]),
        (8, "Lasagne", "main_dish", "meat", ["italian"], "casserole", 4, 70, 45, None, [2, 4]),
        (9, "Pad thai", "main_dish", "meat", ["asian"], None, 2, 20, 10, None, [2, 3]),
        (10, "Pumpkin risotto", "main_dish", "vegan", ["italian"], None, 5, 10, 30, None, [1, 5]),
        (11, "Liver", "main_dish", "meat", [], None, 4, 10, 10, None, [4]),
        (12, "Pancakes", "dessert", "vegetarian", [], None, None, 10, 10, None, []),
    ]
    history = {   # id -> (taste, effort, repeat, every, last_ago)   all ratings 0-10
        1: (8, 2, 7, 14, 1), 2: (7, 2, 5, 30, 2), 4: (9, 5, 8, 20, 30), 5: (6, 0, 5, 10, 60),
        7: (5, 2, 3, 25, 20), 11: (2, 2, 0, 60, 90),
    }
    data = {
        "ingredients": [yr.normalize_ingredient({"ingredient_id": i, "name": n, "side_dish": s, "veg_type": v,
                                                 "category": c}) for i, n, s, v, c in ing],
        "recipes": [{"recipe_id": i, "name": n, "recipe_type": t, "veg_type": v, "origin": o,
                     "recipe_spec": sp, "main_ingredient": m, "prep_minutes": p, "cook_minutes": c,
                     "variant_of": vo, "season": "all", "sweet": False}
                    for i, n, t, v, o, sp, m, p, c, vo, _ in recipes],
        "recipe_ingredients": [{"recipe_id": r[0], "ingredient_id": i} for r in recipes for i in r[10]],
        "history": [],
        "wishlist": [{"recipe_id": 10, "user_id": "u1"}],
        "blacklist": [{"recipe_id": 11, "user_id": "u1"}, {"recipe_id": 6, "user_id": "u2"}],
    }
    for rid, (taste, effort, repeat, every, last_ago) in history.items():
        e = entry(repeat, every, last_ago, count=3)
        n = len(e["dates"])
        data["history"].append({"recipe_id": rid, **e, "taste_rating": [taste] * n, "effort_rating": [effort] * n})
    return data


EXPECTED_NEVER = {1: "cooked yesterday (remove)", 2: "cooked 2 days ago (remove)",
                  3: "variant of last_supper", 8: "prep 70 min (same day)",
                  11: "blacklisted", 12: "dessert (wrong type)"}
NEW_RECIPES = {6, 9}   # allowed + never cooked + not on the wishlist -> pool of new recipes


def run_propose(runs=3000, seed=1, **kw):
    data = example_data()
    rng = random.Random(seed)
    hits, max_same_root = Counter(), 0
    by_id = {r["recipe_id"]: r for r in data["recipes"]}
    for _ in range(runs):
        res = pl.propose(data, user_id="u1", today=TODAY, rng=rng, **kw)   # blacklist (Liver) from data
        hits.update(r["recipe_id"] for r in res)
        roots = Counter(pl.variant_root(r) for r in res)
        max_same_root = max(max_same_root, max(roots.values(), default=0))
    return data, by_id, {rid: hits[rid] / runs for rid in by_id}, max_same_root


def run_draws(runs=10000, seed=1, t=None):
    rng = random.Random(seed)
    hits, together = Counter(), 0
    for _ in range(runs):
        res = pl.draw_proposals(DRAW_SCORES, DRAW_ROOTS, rng=rng, t=t)
        hits.update(res)
        together += "A (20)" in res and "A-rice variant (20)" in res
    return {n: hits[n] / runs for n in DRAW_SCORES}, together


def allowed(data=None, **kw):
    """hard_filter on the example data (user u1) -> sorted recipe_ids."""
    data = data or example_data()
    ds = pl.build_propose_dataset(data, "u1", TODAY)
    kw.setdefault("blacklist", pl.user_blacklist(data, "u1"))
    return sorted(pl.hard_filter(ds, pl.last_supper(data, TODAY), **kw))


def pools(data=None):
    data = data or example_data()
    ds = pl.build_propose_dataset(data, "u1", TODAY)
    return ds, *pl.split_pools(ds, allowed(data))


def server_calls():
    """GET + POST /api/propsals through Flask's test client on the example data (no running server)."""
    from Server import smartfood_server as srv

    class FixedDate(date):          # server uses date.today() -> pin it to TODAY like the example data
        @classmethod
        def today(cls):
            return TODAY

    load_all, real_date = srv.load_all, pl.date
    srv.load_all, pl.date = example_data, FixedDate
    try:
        client = srv.app.test_client()
        get = client.get("/api/propsals?user=u1").get_json()
        post = client.post("/api/propsals", json={"meal_type": "main_dish", "diet": "vegan", "user_id": "u1",
                                                  "include": [], "exclude": ["tomato"], "count": 10}).get_json()
        new = client.get("/api/propsals?user=u1&pool=new&t=99").get_json()
        empty = client.post("/api/propsals", json={"meal_type": "snack", "user_id": "u1"}).get_json()
    finally:
        srv.load_all, pl.date = load_all, real_date
    return get, post, new, empty


def save_keeps_missing_keys():
    """POST /api/all without wishlist (like creation.html / ingredients.html) must not empty
    wishlist.yaml. Runs on temp copies - the real server_data is never written."""
    import tempfile
    from Server import smartfood_server as srv
    files = srv.FILES
    with tempfile.TemporaryDirectory() as tmp:
        srv.FILES = {k: Path(tmp) / p.name for k, p in files.items()}
        try:
            srv.save_all({"wishlist": [{"recipe_id": 1, "user_id": "u1"}], "recipes": []})
            srv.app.test_client().post("/api/all", json={"recipes": [], "ingredients": []})
            return srv.load_all()["wishlist"] == [{"recipe_id": 1, "user_id": "u1"}]
        finally:
            srv.FILES = files


def rating_rejected(**kw) -> bool:
    """rate_recipe with incomplete input must raise (no partial ratings)."""
    full = dict(taste_rating=7, repeat_rating=5, effort_rating=4, actual_prep=10, actual_cook=20)
    try:
        rl.rate_recipe(example_data(), 5, "u1", **(full | kw))
    except ValueError:
        return True
    return False


def cookbook_content(data) -> str:
    """LaTeX content of the cookbook PDF tool (no LaTeX compile) on the example data."""
    sys.path.insert(0, str(ROOT / "Tools"))       # the PDF tool imports YamlEditor top-level
    import generate_cookbook_PDF as cb
    recipes = cb.parse_recipes({"recipes": data["recipes"]})
    ingredients = cb.parse_ingredients({"ingredients": data["ingredients"]})
    links = cb.parse_links({"recipe_ingredients": data["recipe_ingredients"]})
    return cb.generate_content(recipes, ingredients, links, cb.parse_history({"history": data["history"]}))


def real_data():
    """The real Server/server_data/*.yaml (read only). Checks on it must hold for ANY data,
    so they keep working when recipes are added."""
    from Server import smartfood_server as srv
    return srv.load_all()


def real_propose_ok(data, runs=50):
    """propose() on real data: only hard-filter-allowed recipes, never two of one family,
    and as many as possible (k or number of families left)."""
    today = date.today()
    ds = pl.build_propose_dataset(data, None, today)
    allowed_ids = set(pl.hard_filter(ds, pl.last_supper(data, today)))
    families = {pl.variant_root(ds[i]["recipe"]) for i in allowed_ids}
    rng = random.Random(1)
    for _ in range(runs):
        res = [r["recipe_id"] for r in pl.propose(data, today=today, k=10, rng=rng)]
        roots = [pl.variant_root(ds[i]["recipe"]) for i in res]
        if not set(res) <= allowed_ids or len(roots) != len(set(roots)) or len(res) != min(10, len(families)):
            return False
    return True


def bad_field_data():
    """Example data with one wrong value per checked field -> data_problems must find all 8."""
    data = example_data()
    r = data["recipes"][0]   # chicken curry, ingredients rice + chicken
    r.update(origin=["mars"], cooking_method="boil", recipe_spec="pizza", main_ingredient=6)   # 6 = tomato, not in it
    data["recipes"][1]["cook_minutes"] = None                                                  # only prep left
    data["ingredients"][0].update(lactose_free="yes", category="herb", kcal=-5)
    return data


def saved_ingredients_format():
    """Saving through the server (like ingredients.html / creation.html) -> every ingredient in the same
    format, old `spice: true` becomes category spice. Runs on temp copies."""
    import tempfile
    from Server import smartfood_server as srv
    files = srv.FILES
    with tempfile.TemporaryDirectory() as tmp:
        srv.FILES = {k: Path(tmp) / p.name for k, p in files.items()}
        try:
            srv.app.test_client().post("/api/all", json={"ingredients": [
                {"name": "Pepper", "spice": True, "ingredient_id": 1},
                {"ingredient_id": 2, "name": "Flour", "category": "basic", "kcal": 35, "extra": "kept"}]})
            saved = srv.load_all()["ingredients"]
        finally:
            srv.FILES = files
    fields = list(yr.INGREDIENT_FIELDS)
    return (list(saved[0]) == fields and saved[0]["category"] == "spice"
            and list(saved[1])[:len(fields)] == fields and saved[1]["extra"] == "kept")


def ingredients_cli(tmp_dir: Path) -> bool:
    """ingredients_byCommandLine add/edit on a temp copy -> same format, category + nutrition set."""
    sys.path.insert(0, str(ROOT / "Tools"))
    import ingredients_byCommandLine as cli
    path = tmp_dir / "ingredients.yaml"
    yr.update_yaml(path, "ingredients", [])
    real, cli.INGREDIENTS_YAML = cli.INGREDIENTS_YAML, path
    try:
        cli.main(["add", "--name", "Mehl", "--veg-type", "vegan", "--side-dish", "false",
                  "--category", "basic", "--unit", "EL", "--kcal", "35"])
        cli.main(["edit", "--id", "1", "--protein", "1.0"])
        ing = yr.load_yaml(path)["ingredients"][0]
    finally:
        cli.INGREDIENTS_YAML = real
    return list(ing) == list(yr.INGREDIENT_FIELDS) and (ing["category"], ing["kcal"], ing["protein"]) == ("basic", 35, 1.0)


def raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


# ================= sanity checks =================
def sanity_checks():
    """(name, passed) - only for DECIDED behavior (edge-case tables in the notebooks)."""
    def dd(r, every, last_ago, count=4):
        return pl.date_details(entry(r, every, last_ago, count), APP, TODAY)

    def d(r, every, last_ago, count=4):
        x = dd(r, every, last_ago, count)
        return x["date_score"], x["remove"]

    rew = pl.calc_reward
    effort_loss = lambda taste: 1 - rew(taste, 10, 20) / rew(taste, 0, 20)
    damp = lambda name: pl.calc_damping(DAMP_CASES[name], LS, "autumn")
    first_draw = pl.softmax(list(DRAW_SCORES.values()))
    _, together = run_draws(2000)
    p = pl.SWAP_P5 ** (1 / pl.PROPOSAL_COUNT)
    data, _, hits, max_same_root = run_propose(500)
    _, _, hits_new, _ = run_propose(300, pool="new")
    ds, main_pool, new_pool = pools(data)
    ts = pl.calc_total_score
    gluten_data = example_data()
    gluten_data["ingredients"][1]["gluten_free"] = False          # noodles contain gluten
    k3 = pl.propose(data, user_id="u1", today=TODAY, k=3, rng=random.Random(2))
    k10 = pl.propose(data, user_id="u1", today=TODAY, k=10, rng=random.Random(2))
    no_times = example_data()
    for r in no_times["recipes"]:
        if r["recipe_id"] == 9:
            r["prep_minutes"] = r["cook_minutes"] = None
    nt_ds, _, nt_new = pools(no_times)
    nt_scores = [nt_ds[i]["score"] for i in allowed(no_times) if nt_ds[i]["score"] is not None]
    wish_today = example_data()        # veggie pasta cooked exactly 5 days ago -> remove, but not last_supper
    next(h for h in wish_today["history"] if h["recipe_id"] == 5).update(entry(5, 10, 5))
    wish_today["wishlist"].append({"recipe_id": 5, "user_id": "u1"})
    no_wish = example_data()
    next(h for h in no_wish["history"] if h["recipe_id"] == 5).update(entry(5, 10, 5))
    srv_get, srv_post, srv_new, srv_empty = server_calls()
    rd = real_data()
    not_specific = dict(data["recipes"][0], main_ingredient=yr.NOT_SPECIFIC)
    shift_nb = lambda r, m: m * math.exp(-(r - (5 + math.log(1 - 0.9) / 0.3)) * 0.3) + m * 0.9 - m   # notebook form
    empty_app = pl.app_stats({"history": []}, TODAY)
    m = APP["periodcycle_app"]
    cookbook = cookbook_content(data)
    return [
        ("date: never cooked -> 5, not removed", pl.date_score(None, APP, TODAY) == (pl.NEVER_COOKED_DATE, False)),
        ("date: cooked today -> 0 and removed", d(5, None, 0, 1) == (0.0, True)),
        ("date: within b days -> removed", d(5, 7, 3)[1]),
        ("date: exactly b days -> removed (score 0)", d(5, None, pl.ZERO_CROSSING, 1) == (0.0, True)),
        ("date: b + 1 days -> not removed", not d(5, None, pl.ZERO_CROSSING + 1, 1)[1]),
        ("date: <= 2 dates -> amplification 1", dd(5, 14, 14, 2)["amp"] == 1.0 and dd(5, None, 7, 1)["amp"] == 1.0),
        ("date: amp 1 -> 80 % at periodcycle_app", abs(d(5, None, round(m), 1)[0] - 8) < 0.01),
        ("date: >= 3 dates -> target T + amplification", dd(5, 7, 7)["target"] is not None),
        ("date: in [0, 10]", all(0 <= d(r, e, x)[0] <= 10 for r in (0, 3, 5, 8, 10)
                                 for e in (None, 3, 14, 42, 90) for x in (0, 4, 10, 30, 365))),
        ("date: longer ago -> higher", d(5, 30, 40)[0] > d(5, 30, 20)[0]),
        ("date: higher Wdh -> higher", d(9, 30, 20)[0] > d(5, 30, 20)[0] > d(2, 30, 20)[0]),
        ("date: empty repeat_rating -> Wdh 5", d(None, 30, 20)[0] == d(5, 30, 20)[0]),
        ("date: same day twice counts once", pl.date_details(
            {"last_date": "2026-09-01", "dates": ["2026-08-01", "2026-08-01", "2026-08-15", "2026-09-01"]},
            APP, TODAY)["n_dates"] == 3),
        ("shift: 0 at Wdh 5, +34.8 % at 0, -7.8 % at 10", pl.repeat_shift(5, 30) == 0
         and abs(pl.repeat_shift(0, 1) - 0.348) < 1e-3 and abs(pl.repeat_shift(10, 1) + 0.0777) < 1e-3),
        ("shift: same as notebook formula (mean_durchgang)",
         all(abs(pl.repeat_shift(r, 30) - shift_nb(r, 30)) < 1e-9 for r in range(11))),
        ("correction: 0 at mean = periodcycle_app, Wdh 5", abs(pl.correction_days(m, 5, 5, APP)) < 1e-9),
        ("correction: points towards periodcycle_app",
         pl.correction_days(m + 15, 5, 5, APP) < 0 < pl.correction_days(m - 15, 5, 5, APP)),
        ("correction: uses the recipe's own mean (shift scales with mean)",
         pl.correction_days(10, 0, 0, APP) - pl.correction_days(10, 0, 5, APP) == pl.repeat_shift(0, 10)),
        ("amplification: 5.05 at T", abs(pl.amplification(20, 20) - 5.05) < 1e-9),
        ("app: no history -> usage 3, rotation 5", empty_app["count_usage_app"] == pl.EMPTY_USAGE_DAYS
         and empty_app["count_recipes_twice"] == pl.MIN_ROTATION_RECIPES),
        ("app: periodcycle_app >= 7 -> tau > 0", pl.app_stats({"history": [
            {"dates": [(TODAY - timedelta(days=i)).isoformat() for i in range(25)]}]}, TODAY)["tau"] > 0
         and empty_app["periodcycle_app"] >= pl.MIN_PERIODCYCLE),
        ("reward: in [0, 10]", all(0 <= rew(t, e, mi) <= 10
                                    for t in range(0, 11) for e in range(0, 11) for mi in (0, 30, 60, 118))),
        ("reward: taste 0 -> 0", rew(0, 0, 20) == 0),
        ("reward: quick, tasty, low effort -> ~10", abs(rew(10, 1, 20) - 9.80) < 0.01),
        ("reward: bad taste + low effort < great taste + high effort", rew(2, 0, 30) < rew(10, 10, 30)),
        ("reward: higher taste -> higher", all(rew(t + 1, 5, 30) > rew(t, 5, 30) for t in range(0, 10))),
        ("reward: less effort -> higher", all(rew(8, e, 30) > rew(8, e + 1, 30) for e in range(0, 10))),
        ("reward: effort matters more for tasty dishes (-26 % vs -50 %)",
         abs(effort_loss(2) - 0.263) < 1e-3 and abs(effort_loss(10) - 0.5) < 1e-9),
        ("reward: 50 min -> half", abs(rew(10, 0, 50) - 5) < 1e-9),
        ("reward: no ratings -> midpoint 5 / 5",
         pl.reward_score({"prep_minutes": 10, "cook_minutes": 20}, None) == rew(5, 5, 30)),
        ("reward: cooked, no times -> 45 min",
         pl.reward_details({}, entry(5, 7, 10))["minutes"] == pl.MISSING_TIME),
        ("reward: never cooked, no times -> no reward (median later)", pl.reward_score({}, None) is None),
        ("reward: negative time -> max(0, time)", rew(8, 5, -30) == rew(8, 5, 0)),
        ("reward: recipe over days -> no overflow", rew(8, 5, 5 * 24 * 60) == 0),
        ("damp: soup after soup x0.2", abs(damp("Tomato soup")[0] - 0.2) < 1e-9),
        ("damp: nothing in common -> unchanged", damp("Veggie pasta")[:2] == (1.0, 3)),
        ("damp: every rule fires max. once", all(len(log) == len(set(log)) for log in
                                                  (damp(n)[2] for n in DAMP_CASES))),
        ("damp: same meat type -> -3", "same meat -3" in damp("Butter chicken")[2]),
        ("damp: same meat in 2 meals counts twice in len", len(LS["meats"]) == 2),
        ("damp: other meat type -> no -3, only x(1-0.1*n)", damp("Beef burger")[:2] == (1 - 0.1 * 2, 3)),
        ("damp: same main, neither meat nor side -> -3", "main -3" in damp("Pumpkin curry")[2]),
        ("damp: same main, it is meat -> x0.9", "main=meat/side x0.9" in damp("Butter chicken")[2]),
        ("damp: meat factor clamped at 0", pl.calc_damping(F(meat="x"), {**LS, "meats": ["c"] * 12}, "autumn")[0] == 0),
        ("damp: main is a side_dish ingredient (attribute from ingredients.yaml)",
         pl.recipe_features(dict(data["recipes"][4], main_ingredient=2), data)["main_meat_or_side"]),
        ("damp: main not in own ingredients -> error",
         raises(lambda: pl.recipe_features(dict(data["recipes"][0], main_ingredient=6), data))),
        ("damp: main not in ingredients.yaml -> error",
         raises(lambda: pl.recipe_features(dict(data["recipes"][0], main_ingredient=99), data))),
        ("score: wishlist always raises the score",
         all(ts(5, 5, mu, o, True) > ts(5, 5, mu, o, False) for mu in (1, 0.5, 0.2, 0.13) for o in (3, 0, -12))),
        ("score: undamped wishlist part survives full damping",
         ts(0, 0, 0.13, 0, True) - ts(0, 0, 0.13, 0, False) >= pl.WISHLIST_SCORE / pl.WISHLIST_UNDAMPED),
        ("draw: softmax probabilities sum to 1", abs(sum(first_draw) - 1) < 1e-9),
        ("draw: negative score still drawable (p > 0)", first_draw[-1] > 0),
        ("draw: higher score -> higher probability", all(a >= b for a, b in zip(first_draw, first_draw[1:]))),
        ("draw: recipe + variant never together", together == 0),
        ("draw: T default 4, clamped to [1, 10]",
         pl.clamp_t(None) == 4 and pl.clamp_t(0) == 1 and pl.clamp_t(99) == 10),
        ("swap: P(>=1 swap in 5) = 1 - SWAP_P5", abs((1 - p ** pl.PROPOSAL_COUNT) - (1 - pl.SWAP_P5)) < 1e-9),
        ("pools: never cooked -> new pool, cooked + wishlist -> main pool",
         set(new_pool) == NEW_RECIPES and set(main_pool) == {4, 5, 7, 10}),
        ("pools: never cooked without times -> median score",
         nt_new[9] == pl.statistics.median(nt_scores) and nt_ds[9]["score"] is None),
        ("pools: wishlist overrides remove", 5 in allowed(wish_today) and 5 not in allowed(no_wish)),
        ("app: last_supper = recipes cooked <= 4 days ago", pl.last_supper(data, TODAY) == [1, 2]),
        ("app: butter chicken damped by chicken + rice", {"same meat -3", "side -3"} <= set(ds[4]["damp_rules"])),
        ("app: wishlist recipe flagged", ds[10]["wishlist"] and not ds[9]["wishlist"]),
        ("app: hard-filtered recipes never proposed", all(hits[i] == 0 for i in EXPECTED_NEVER)),
        ("app: never two variants of one recipe in a list", max_same_root == 1),
        ("app: every allowed recipe can be proposed (new ones via fill / swap)",
         all(hits[i] > 0 for i in hits if i not in EXPECTED_NEVER)),
        ("app: pool=new -> only never cooked recipes", {i for i, h in hits_new.items() if h} == NEW_RECIPES),
        ("filter: same day only above 60 min (60 ok, 61 out)",
         not pl.is_same_day({"prep_minutes": 60, "cook_minutes": 60}) and pl.is_same_day({"cook_minutes": 61})),
        ("filter: blacklist per user from data", pl.user_blacklist(data, "u1") == {11}
         and pl.user_blacklist(data, "u2") == {6} and pl.user_blacklist(data, None) == set()),
        ("filter: no extra filters -> all allowed", allowed() == [4, 5, 6, 7, 9, 10]),
        ("filter: include by name (case-insensitive)", allowed(include=["chicken"]) == [4, 9]),
        ("filter: include by ingredient_id", allowed(include=[4]) == [6]),
        ("filter: include needs ALL ingredients", allowed(include=["chicken", "rice"]) == [4]),
        ("filter: exclude by name", allowed(exclude=["Rice"]) == [5, 6, 7, 9]),
        ("filter: allergy -> ingredient with gluten_free False removed",
         allowed(gluten_data, allergies=["gluten"]) == [4, 6, 7, 10]),
        ("filter: allergy field missing -> not filtered", allowed(allergies=["gluten", "lactose"]) == allowed()),
        ("filter: diet vegetarian includes vegan", allowed(diet="vegetarian") == [5, 7, 10]),
        ("filter: diet nonvegan", allowed(diet="nonvegan") == [4, 6, 9]),
        ("filter: diet meat (exact)", allowed(diet="meat") == [4, 6, 9]),
        ("propose: k=3 -> 3 recipes", len(k3) == 3),
        ("propose: k > candidates -> every candidate once",
         sorted(r["recipe_id"] for r in k10) == allowed()),
        ("server: GET /api/propsals -> 5 allowed recipes, new ones flagged",
         len(srv_get["main_dish"]) == pl.PROPOSAL_COUNT and {r["id"] for r in srv_get["main_dish"]} <= set(allowed())
         and all(r["is_new"] == (r["id"] in NEW_RECIPES | {10}) for r in srv_get["main_dish"])),   # 10: wishlist, never cooked
        ("server: POST vegan, exclude tomato -> only pumpkin risotto", [r["id"] for r in srv_post["recipes"]] == [10]),
        ("server: GET pool=new -> only new recipes, t clamped to 10",
         {r["id"] for r in srv_new["main_dish"]} == NEW_RECIPES and srv_new["t"] == 10),
        ("server: nothing found -> empty list + message", srv_empty["recipes"] == [] and srv_empty.get("message")),
        ("server: saving without wishlist/blacklist keeps them", save_keeps_missing_keys()),
        ("rating: effort missing -> rejected", rating_rejected(effort_rating=None)),
        ("rating: effort above 10 -> rejected", rating_rejected(effort_rating=11)),
        ("rating: only one time -> rejected", rating_rejected(actual_cook=None)),
        ("rating: complete rating accepted", not rating_rejected()),
        ("rating: no history -> prefill 5 / 5 / 5", [rl.default_ratings(data, 9)[k] for k in
                                                     ("taste_rating", "repeat_rating", "effort_rating")] == [5, 5, 5]),
        ("cookbook PDF: ratings from history, else recipe defaults (Standard)",
         "Geschmack 8,0/10 •" in cookbook and "Geschmack 5,0/10 (Standard)" in cookbook),
        ("cookbook PDF: no reward / times cooked / last date", not any(
            s in cookbook for s in ("Reward", "gekocht", "zuletzt"))),
        ("cookbook PDF: season, type, cuisine", r"Saison: Ganzjährig • Typ: Fleisch • Küche: Indisch" in cookbook),
        ("cookbook PDF: main ingredient bold", r"\textbf{Chicken}" in cookbook and r"\textbf{Tomato}" in cookbook),
        ("cookbook PDF: Zutaten / Grundzutaten / Gewürze split",
         all(s in cookbook for s in (r"\textbf{Zutaten:}", r"\textbf{Grundzutaten:}", r"\textbf{Gewürze:}"))
         and cookbook.index("Water") < cookbook.index("Salt")),
        ("ingredients: normalize -> same fields + order, old spice flag -> category",
         list(yr.normalize_ingredient({"name": "x", "spice": True})) == list(yr.INGREDIENT_FIELDS)
         and yr.normalize_ingredient({"name": "x", "spice": True})["category"] == "spice"),
        ("ingredients: server save keeps one format", saved_ingredients_format()),
        ("ingredients: command line tool writes the same format", ingredients_cli(Path(tempfile.mkdtemp()))),
        ("real data: every ingredient in the same format",
         all(list(i)[:len(yr.INGREDIENT_FIELDS)] == list(yr.INGREDIENT_FIELDS) for i in rd["ingredients"])),
        ("fields: example data valid", yr.data_problems(data) == []),
        ("fields: every wrong value found", len(yr.data_problems(bad_field_data())) == 8),
        ("fields: main_ingredient 'not specific' -> no main rule",
         pl.recipe_features(not_specific, data)["main"] is None),
        ("real data: field values valid (YamlEditor.data_problems)", yr.data_problems(rd) == []),
        ("real data: propose() only allowed recipes, one per family", real_propose_ok(rd)),
    ]


def test_sanity():
    failed = [name for name, ok in sanity_checks() if not ok]
    assert not failed, failed


# ================= report =================
def main():
    print(f"today = {TODAY} ({pl.current_season(TODAY)}), knobs from Tools/ProposeLogic.py\n")

    print(f"=== II.1 date_score - periodcycle_app = {APP['periodcycle_app']:.0f} days, tau = {APP['tau']:.1f} ===")
    print(f"{'case':40} {'mean':>5} {'std':>5} {'T':>6} {'amp':>5} {'score':>6} {'removed':>8}")
    fmt = lambda v, f: "-" if v is None else format(v, f)
    for name, r, every, last_ago, count in DATE_CASES:
        x = pl.date_details(entry(r, every, last_ago, count), APP, TODAY)
        print(f"{name:40} {fmt(x['mean'], '5.1f'):>5} {fmt(x['std'], '5.1f'):>5} {fmt(x['target'], '6.1f'):>6} "
              f"{fmt(x['amp'], '5.2f'):>5} {x['date_score']:6.2f} {str(x['remove']):>8}")

    print("\n=== II.2 timescore ===")
    print({t: round(pl.timescore(t), 2) for t in (10, 20, 30, 40, 50, 60, 70, 90)})
    print("\n=== II.2 reward (time 20 min) - rows: taste 0-10, cols: effort 0-10 (10 = high effort) ===")
    print("taste\\effort " + "".join(f"{e:>7}" for e in range(0, 11, 2)) + "   effort loss")
    for t in range(10, -1, -2):
        row = [pl.calc_reward(t, e, 20) for e in range(0, 11, 2)]
        loss = 1 - row[-1] / row[0] if row[0] else 0
        print(f"{t:>12} " + "".join(f"{v:7.2f}" for v in row) + f"   {loss:6.0%}")

    print("\n=== II.3 damping vs last_supper = chicken curry, pumpkin soup, chicken wok ===")
    for name, feat in DAMP_CASES.items():
        mu, o, log = pl.calc_damping(feat, LS, "autumn")
        print(f"{name:15} mult={mu:.2f} offset={o:+3}  score(base 12)={12 * mu + o:6.2f}   {', '.join(log)}")

    print(f"\n=== III softmax draw, 5 without putting back (10000 runs) - SOFTMAX_T = {pl.SOFTMAX_T} ===")
    temps = sorted({1, 3, 5, 10, pl.SOFTMAX_T})
    results = {t: run_draws(t=t) for t in temps}
    print(f"{'recipe (score)':20}" + "".join(f"{'T=' + str(t):>9}" for t in temps))
    for n in DRAW_SCORES:
        print(f"{n:20}" + "".join(f"{results[t][0][n]:9.1%}" for t in temps))

    p = pl.SWAP_P5 ** (1 / pl.PROPOSAL_COUNT)
    print(f"\n=== Swap === p = {p:.4f}, swap prob per slot = {1 - p:.4f}, "
          f"P(>=1 swap in 5) = {1 - p ** pl.PROPOSAL_COUNT:.3f}")

    print("\n=== Full pipeline pl.propose() on example data (3000 runs, blacklist = Liver, wishlist = Pumpkin risotto) ===")
    data, by_id, hits, _ = run_propose()
    ds, main_pool, new_pool = pools(data)
    print(f"{'recipe':26} {'pool':>5} {'date':>5} {'rew':>5} {'mult':>5} {'off':>4} {'score':>6} {'in list':>8}  note")
    for rid, r in by_id.items():
        x = ds[rid]
        pool = "main" if rid in main_pool else "new" if rid in new_pool else "-"
        score = main_pool.get(rid, new_pool.get(rid, x["score"]))
        print(f"{r['name']:26} {pool:>5} {x['date_score']:5.2f} {fmt(x['reward_score'], '5.2f'):>5} "
              f"{x['damp_score_mult']:5.2f} {x['damp_score_offset']:+4} {fmt(score, '6.2f'):>6} {hits[rid]:8.1%}  "
              f"{EXPECTED_NEVER.get(rid, '')}")

    print("\n=== Real data (Server/server_data) - per recipe details: docs/Testing/test_with_data.ipynb ===")
    rd = real_data()
    recipes, ingredients = rd["recipes"], rd["ingredients"]
    print(f"{len(recipes)} recipes, {len(ingredients)} ingredients, app: {pl.app_stats(rd)}")
    for prob in yr.data_problems(rd):
        print(f"  PROBLEM: {prob}")
    res = pl.propose(rd, k=10, rng=random.Random(1))
    print(f"  propose() today -> {[r.get('name') for r in res]}")

    print("\n=== Sanity checks ===")
    checks = sanity_checks()
    for name, ok in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
