"""Example scenarios for the propose logic in Tools/ProposeLogic.py (docs/ProposeLogic.md).

Run from the project root (the server does NOT need to run):
       python tests/test_propose_plan.py      (prints all tables + sanity checks)
  or:  python -m pytest tests/test_propose_plan.py

All formulas and tuning knobs live in Tools/ProposeLogic.py - change them there and re-run.
This file only builds example data (history entries, recipes, ...) and checks the results.
Scales: taste 0-10, repeat 1-5, effort 1-5 (1 = low effort, 5 = high effort).
"""
from __future__ import annotations
import math
import random
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # project root -> "Tools" importable
from Tools import ProposeLogic as pl  # noqa: E402

TODAY = date(2026, 9, 28)   # fixed, so every run gives the same numbers (autumn)


# ================= scenario builders =================
def entry(repeat=None, every=None, last_ago=None, count=3):
    """History entry like in history.yaml: cooked `count` times, every `every` days,
    last time `last_ago` days ago. last_ago=None -> never cooked."""
    if last_ago is None:
        return {"repeat_rating": [repeat]} if repeat else {}
    last = TODAY - timedelta(days=last_ago)
    n = count if every else 1
    dates = sorted((last - timedelta(days=i * (every or 0))).isoformat() for i in range(n))
    return {"last_date": last.isoformat(), "dates": dates,
            "repeat_rating": [repeat] * n if repeat else []}


def F(season="all", origin=(), spec=None, sweet=False, side=None, meat=None, main=None):
    """Damping features of one recipe (same shape as pl.recipe_features)."""
    specs = ({spec} & pl.DAMP_SPECS) | ({"sweet"} if sweet else set())
    return {"season": season, "origins": set(origin), "method": None, "specs": specs,
            "sides": {side} if side else set(), "main": main, "meats": {meat} if meat else set()}


DATE_CASES = [   # name, repeat, every, last_ago, count
    ("never cooked", 1, None, None, 0),
    ("cooked today, once, r=4", 4, None, 0, 1),
    ("once, 7 days ago, r=3", 3, None, 7, 1),
    ("every 3 days, last 3 ago, r=5", 5, 3, 3, 3),
    ("every 7 days, last exactly 4 ago, r=5", 5, 7, 4, 3),
    ("every 7 days, last 7 ago, r=5", 5, 7, 7, 3),
    ("every 7 days, last 14 ago, r=5", 5, 7, 14, 3),
    ("every 20 days, last 13 ago, r=4", 4, 20, 13, 3),
    ("every 20 days, last 40 ago, r=4", 4, 20, 40, 3),
    ("every 90 days, last 90 ago, r=5", 5, 90, 90, 3),
    ("every 90 days, last 10 ago, r=5", 5, 90, 10, 3),
]

LAST_SUPPER = [
    F(origin=["indian"], side="rice", meat="chicken", main="chicken"),     # chicken curry
    F(season="autumn", spec="soup", main="pumpkin"),                       # pumpkin soup
    F(origin=["asian"], side="rice", meat="chicken", main="chicken"),      # chicken wok
]
LS = pl.merge_last_supper(LAST_SUPPER)
DAMP_CASES = {
    "Butter chicken": F(origin=["indian"], side="rice", meat="chicken", main="chicken"),
    "Tomato soup": F(spec="soup", main="tomato"),
    "Veggie pasta": F(origin=["italian"], side="noodles", main="vegetables"),
    "Summer salad": F(season="summer", spec="salad"),
    "Beef burger": F(origin=["american"], meat="beef", main="beef"),
    "Pumpkin curry": F(origin=["indian"], side="rice", main="pumpkin"),
}

DRAW_SCORES = {"A (20)": 20, "A-rice variant (20)": 20, "B (10)": 10, "G (8)": 8, "C (5)": 5,
               "D (2)": 2, "E (0.5)": 0.5, "F (-4)": -4}
DRAW_ROOTS = {n: n for n in DRAW_SCORES} | {"A-rice variant (20)": "A (20)"}


def example_data():
    """Small fake database in the shape of server_data/*.yaml (+ planned fields from doc V)."""
    ing = [(1, "Rice", True, "vegan"), (2, "Noodles", True, "vegan"), (3, "Chicken", False, "meat"),
           (4, "Beef", False, "meat"), (5, "Pumpkin", False, "vegan"), (6, "Tomato", False, "vegan")]
    recipes = [   # id, name, type, veg, origin, spec, main, prep, cook, variant_of, ingredients
        (1, "Chicken curry", "main_dish", "meat", ["indian"], None, 3, 15, 25, None, [1, 3]),
        (2, "Pumpkin soup", "main_dish", "vegan", [], "soup", 5, 15, 20, None, [5]),
        (3, "Chicken curry (noodles)", "main_dish", "meat", ["indian"], None, 3, 15, 25, 1, [2, 3]),
        (4, "Butter chicken", "main_dish", "meat", ["indian"], None, 3, 15, 30, None, [1, 3]),
        (5, "Veggie pasta", "main_dish", "vegan", ["italian"], None, 2, 10, 15, None, [2, 6]),
        (6, "Beef burger", "main_dish", "meat", ["american"], None, 4, 15, 15, None, [4]),
        (7, "Tomato soup", "main_dish", "vegan", [], "soup", 6, 10, 20, None, [6]),
        (8, "Lasagne", "main_dish", "meat", ["italian"], "casserole", 4, 70, 45, None, [2, 4]),
        (9, "Pad thai", "main_dish", "meat", ["asian"], None, 2, 20, 10, None, [2, 3]),
        (10, "Pumpkin risotto", "main_dish", "vegan", ["italian"], None, 5, 10, 30, None, [1, 5]),
        (11, "Liver", "main_dish", "meat", [], None, 4, 10, 10, None, [4]),
        (12, "Pancakes", "dessert", "vegetarian", [], None, None, 10, 10, None, []),
    ]
    history = {   # id -> (taste, effort, repeat, every, last_ago)
        1: (8, 2, 4, 14, 1), 2: (7, 2, 3, 30, 2), 4: (9, 3, 5, 20, 30), 5: (6, 1, 3, 10, 60),
        7: (5, 2, 2, 25, 20), 11: (2, 2, 1, 60, 90),
    }
    data = {
        "ingredients": [{"ingredient_id": i, "name": n, "side_dish": s, "veg_type": v} for i, n, s, v in ing],
        "recipes": [{"recipe_id": i, "name": n, "recipe_type": t, "veg_type": v, "origin": o,
                     "recipe_spec": sp, "main_ingredient": m, "prep_minutes": p, "cook_minutes": c,
                     "variant_of": vo, "season": "all", "sweet": False}
                    for i, n, t, v, o, sp, m, p, c, vo, _ in recipes],
        "recipe_ingredients": [{"recipe_id": r[0], "ingredient_id": i} for r in recipes for i in r[10]],
        "history": [],
        "wishlist": [{"recipe_id": 10, "user_id": "u1"}],
    }
    for rid, (taste, effort, repeat, every, last_ago) in history.items():
        e = entry(repeat, every, last_ago, count=3)
        n = len(e["dates"])
        data["history"].append({"recipe_id": rid, **e, "taste_rating": [taste] * n, "effort_rating": [effort] * n})
    return data


EXPECTED_NEVER = {1: "cooked yesterday (remove)", 2: "cooked 2 days ago (remove)",
                  3: "variant of last_supper", 8: "prep 70 min (same day)",
                  11: "blacklisted", 12: "dessert (wrong type)"}


def run_propose(runs=3000, seed=1):
    data = example_data()
    rng = random.Random(seed)
    hits, max_same_root = Counter(), 0
    by_id = {r["recipe_id"]: r for r in data["recipes"]}
    for _ in range(runs):
        res = pl.propose(data, user_id="u1", today=TODAY, blacklist={11}, rng=rng)
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


# ================= sanity checks =================
def sanity_checks():
    """(name, passed) - only for DECIDED behavior (see doc VII)."""
    def d(r, every, last_ago, count=3):
        return pl.date_score(entry(r, every, last_ago, count), TODAY)
    rew = pl.calc_reward
    effort_loss = lambda taste: 1 - rew(taste, 5, 20) / rew(taste, 1, 20)
    damp = lambda name: pl.calc_damping(DAMP_CASES[name], LS, "autumn")
    first_draw = pl.softmax(list(DRAW_SCORES.values()))
    _, together = run_draws(2000)
    p = pl.SWAP_P5 ** (1 / pl.PROPOSAL_COUNT)
    data, _, hits, max_same_root = run_propose(500)
    ds = pl.build_propose_dataset(data, "u1", TODAY)
    ts = pl.calc_total_score
    return [
        ("date: just cooked -> 0 and removed", d(4, None, 0, 1) == (0.0, True)),
        ("date: within DATE_BLOCK days -> removed", d(5, 3, 3)[1]),
        ("date: exactly DATE_BLOCK days -> removed (score 0)", d(5, 7, pl.DATE_BLOCK) == (0.0, True)),
        ("date: DATE_BLOCK + 1 days -> not removed", not d(5, 7, pl.DATE_BLOCK + 1)[1]),
        ("date: rarely cooked, long ago -> high", d(5, 90, 90)[0] > 9),
        ("date: never cooked -> NEVER_COOKED_DATE", pl.date_score(None, TODAY) == (pl.NEVER_COOKED_DATE, False)),
        ("date: in [0, 10]", all(0 <= d(r, e, x)[0] <= 10 for r in range(1, 6)
                                 for e in (None, 3, 14, 42, 90) for x in (0, 4, 10, 30, 365))),
        ("date: longer ago -> higher", d(4, 20, 40)[0] > d(4, 20, 13)[0]),
        ("date: higher repeat -> higher", d(5, 20, 13)[0] > d(3, 20, 13)[0]),
        ("date: empty repeat_rating -> EMPTY_REPEAT", d(None, 20, 13)[0] == d(pl.EMPTY_REPEAT, 20, 13)[0]),
        ("reward: in [0, 10]", all(0 <= rew(t, e, m) <= 10
                                    for t in range(0, 11) for e in range(1, 6) for m in (0, 30, 60, 118))),
        ("reward: taste 0 -> 0", rew(0, 1, 20) == 0),
        ("reward: quick, tasty, low effort -> ~10", rew(10, 1, 20) > 9.5),
        ("reward: bad taste punished more than low effort helps", rew(2, 1, 20) < rew(10, 5, 20)),
        ("reward: higher taste -> higher", all(rew(t + 1, 3, 30) > rew(t, 3, 30) for t in range(0, 10))),
        ("reward: less effort -> higher", all(rew(8, e, 30) > rew(8, e + 1, 30) for e in range(1, 5))),
        ("reward: effort matters more for tasty dishes", effort_loss(10) > effort_loss(2)),
        ("reward: 50 min -> half of 0 min", abs(rew(10, 1, 50) / rew(10, 1, 0) - 0.5) < 0.01),
        ("reward: never cooked -> taste 8, effort 3",
         pl.reward_score({"prep_minutes": 10, "cook_minutes": 20}, None) == rew(8, 3, 30)),
        ("reward: missing times -> 45 min", pl.total_minutes({}) == pl.MISSING_TIME),
        ("damp: soup after soup x0.2", abs(damp("Tomato soup")[0] - 0.2) < 1e-9),
        ("damp: nothing in common -> unchanged", damp("Veggie pasta")[:2] == (1.0, 3)),
        ("damp: every rule fires max. once", all(len(log) == len(set(log)) for log in
                                                  (damp(n)[2] for n in DAMP_CASES))),
        ("damp: same meat type -> -5", "same meat -5" in damp("Butter chicken")[2]),
        ("damp: other meat type -> no -5, only x(1-0.1*n)",
         damp("Beef burger")[:2] == (1 - 0.1 * len(LS["meats"]), 3)),
        ("damp: same main, neither meat nor side -> -3", "main -3" in damp("Pumpkin curry")[2]),
        ("damp: offset in [-12, 3]", all(-12 <= damp(n)[1] <= 3 for n in DAMP_CASES)),
        ("score: wishlist always raises the score",
         all(ts(5, 5, m, o, True) > ts(5, 5, m, o, False) for m in (1, 0.5, 0.2, 0.13) for o in (3, 0, -12))),
        ("score: undamped wishlist part survives full damping",
         ts(0, 0, 0.13, 0, True) - ts(0, 0, 0.13, 0, False) >= pl.WISHLIST_SCORE / pl.WISHLIST_UNDAMPED),
        ("score: range [-12, 35]", all(-12 <= ts(a, b, m, o, w) <= 35 for a in (0, 10) for b in (0, 10)
                                       for m in (0.13, 1) for o in (-12, 3) for w in (False, True))),
        ("draw: softmax probabilities sum to 1", abs(sum(first_draw) - 1) < 1e-9),
        ("draw: negative score still drawable (p > 0)", first_draw[-1] > 0),
        ("draw: higher score -> higher probability", all(a >= b for a, b in zip(first_draw, first_draw[1:]))),
        ("draw: recipe + variant never together", together == 0),
        ("swap: P(>=1 swap in 5) = 1 - SWAP_P5", abs((1 - p ** pl.PROPOSAL_COUNT) - (1 - pl.SWAP_P5)) < 1e-9),
        ("app: last_supper = recipes cooked <= 4 days ago", pl.last_supper(data, TODAY) == [1, 2]),
        ("app: butter chicken damped by chicken + rice", {"same meat -5", "side -3"} <= set(ds[4]["damp_rules"])),
        ("app: wishlist recipe flagged", ds[10]["wishlist"] and not ds[9]["wishlist"]),
        ("app: hard-filtered recipes never proposed", all(hits[i] == 0 for i in EXPECTED_NEVER)),
        ("app: never two variants of one recipe in a list", max_same_root == 1),
        ("app: every allowed recipe can be proposed",
         all(hits[i] > 0 for i in hits if i not in EXPECTED_NEVER)),
    ]


def test_sanity():
    failed = [name for name, ok in sanity_checks() if not ok]
    assert not failed, failed


# ================= report =================
def main():
    print(f"today = {TODAY} ({pl.current_season(TODAY)}), knobs from Tools/ProposeLogic.py\n")

    print("=== II.1 date_score (tanh) ===")
    print(f"{'case':40} {'factor':>6} {'score':>6} {'removed':>8}")
    for name, r, every, last_ago, count in DATE_CASES:
        e = entry(r, every, last_ago, count)
        score, removed = pl.date_score(e, TODAY)
        f = f"{pl.date_factor(every if every and count >= 2 else None):.2f}" if last_ago is not None else "-"
        print(f"{name:40} {f:>6} {score:6.2f} {str(removed):>8}")
    print("\n50 % of max (tanh = 0.5) reached after dist_last days:")
    for f in (4, 3, 2, 1):
        dl = pl.DATE_BLOCK + math.atanh(0.5) * pl.DATE_SLOPE / f
        print(f"  factor {f}: {dl:5.1f} days")

    print("\n=== II.2 timescore ===")
    print({t: round(pl.timescore(t), 2) for t in (10, 20, 30, 40, 50, 60, 70, 90)})
    print("\n=== II.2 reward (time 20 min) - rows: taste 0-10, cols: effort 1-5 (5 = high effort) ===")
    print("taste\\effort " + "".join(f"{e:>7}" for e in range(1, 6)) + "   effort loss")
    for t in range(10, -1, -2):
        row = [pl.calc_reward(t, e, 20) for e in range(1, 6)]
        loss = 1 - row[-1] / row[0] if row[0] else 0
        print(f"{t:>12} " + "".join(f"{v:7.2f}" for v in row) + f"   {loss:6.0%}")

    print("\n=== II.3 damping vs last_supper = chicken curry, pumpkin soup, chicken wok ===")
    for name, feat in DAMP_CASES.items():
        m, o, log = pl.calc_damping(feat, LS, "autumn")
        print(f"{name:15} mult={m:.2f} offset={o:+3}  score(base 12)={12 * m + o:6.2f}   {', '.join(log)}")

    print(f"\n=== III total score (date 5, reward 5): wishlist {pl.WISHLIST_SCORE}, "
          f"undamped part {pl.WISHLIST_SCORE / pl.WISHLIST_UNDAMPED:g} ===")
    print(f"{'damping':30} {'no wishlist':>12} {'wishlist':>10} {'gain':>6}")
    for label, m, o in [("none (season +3)", 1, 3), ("soup after soup (x0.2, +3)", 0.2, 3),
                        ("same chicken (x0.81, -6)", 0.81, -6), ("worst case (x0.13, -12)", 0.13, -12)]:
        a, b = pl.calc_total_score(5, 5, m, o, False), pl.calc_total_score(5, 5, m, o, True)
        print(f"{label:30} {a:12.2f} {b:10.2f} {b - a:+6.2f}")

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
    ds = pl.build_propose_dataset(data, "u1", TODAY)
    print(f"{'recipe':26} {'date':>5} {'rew':>5} {'mult':>5} {'off':>4} {'score':>6} {'in list':>8}  note")
    for rid, r in by_id.items():
        x = ds[rid]
        print(f"{r['name']:26} {x['date_score']:5.2f} {x['reward_score']:5.2f} {x['damp_score_mult']:5.2f} "
              f"{x['damp_score_offset']:+4} {x['score']:6.2f} {hits[rid]:8.1%}  {EXPECTED_NEVER.get(rid, '')}")

    print("\n=== Sanity checks ===")
    checks = sanity_checks()
    for name, ok in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
