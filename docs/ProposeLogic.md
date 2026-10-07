# Propose Logic – Formulas & Sanity Checks

Every formula is written down here as planned or as implemented, so code and idea can be checked against each other later.

> **Status** – shown next to every function heading. Code: [Tools/ProposeLogic.py](../Tools/ProposeLogic.py), used by the server in `GET` + `POST /api/propsals`.
>
> ⬜ not started · ✅ implemented in logic · ❌ logic error · ❓ open question (VIII) · 🧪 has test case ([tests/test_propose_plan.py](../tests/test_propose_plan.py), IX)
>
> 💡 = suggestion, not decided yet · ⚠️ = found by logic test (IX)
>
> All tuning knobs are constants at the top of `ProposeLogic.py`. Example scenarios: IX.

---

# I. Overview – `propose()`, `build_propose_dataset()` ✅ 🧪

1. Load all data (could be inefficient)
   1. Recipes
   2. History
   3. Recipe ingredients
   4. Wishlist
   5. Blacklisted recipes (user doesn't like them at all)
2. From history calculate **date_score** (II.1)
   - distances in `dates` (array[date])
   - distance last cooked ↔ today: `last_date` (date)
   - repeat score: `repeat_rating` (array[int])
   - sets `remove = True` if cooked within the last 4 days
3. **Hard filters** (II.4) – remove before the other scores
   - `remove == True` from date_score (this already removes the last_supper recipes themselves)
   - variants of last_supper – they have their own history, so date_score doesn't catch them
   - blacklisted recipes
   - wrong `recipe_type` / `veg_type` (existing `filter_recipes`)
   - same-day cooking: `prep_minutes` or `cook_minutes` > 60 (II.2)
   - include / exclude ingredients (search filter)
   - lactose etc. allergies
4. From history estimate effort vs. result: **reward_score** (II.2)
   - `taste_rating`, `effort_rating`, `prep_minutes`, `cook_minutes`
5. Damp meals similar to recently cooked ones: **damp_score** (II.3)
6. Generate list: total score → softmax draw of 5 → swapping (III)

# II. Methods

## 1. `date_score()` → date_score, remove ✅ 🧪 ❓ (VIII.2)

```
take dates (without today)
dist_last = distance last_date ↔ today, floored to days
repeat    = mean(repeat_rating)

if len(dates) <= 1:
    factor = 1                                     # no distance between dates yet
else:
    avg_dist = mean distance between dates, floored to days
    factor   = max(1, 4 - avg_dist/14)             # repeating every 14 days results in a good score
    TODO later: calibrate with number of recipes

factor → g(factor, dist_last) ∈ (0, 1)
       → tanh(factor/c · (x - b))                  with c = 30, b = 4

date_score = 10/5 · repeat · tanh(factor/30 · (dist_last - 4))
if date_score <= 0:
    remove = True
date_score = max(0, date_score)

Result: date_score ∈ [0, 10]
```

Tuning knobs in `ProposeLogic.py`: `DATE_SLOPE` (c = 30), `DATE_BLOCK` (b = 4), `NEVER_COOKED_DATE`, `EMPTY_REPEAT`.

**Ranges**

| Symbol | Range | Meaning |
|---|---|---|
| `factor` | 1 – 4 | 4 = cooked very often (avg_dist → 0), 1 = avg_dist ≥ 42 days or ≤ 1 date |
| `repeat` | 1 – 5 | desire to repeat; seed for uncooked recipes = 1 |
| 50 % of max | 8 – 20.5 days | when `tanh(factor/30 · (dist_last − 4)) = 0.5` → factor 4: 8.1 d, 3: 9.5 d, 2: 12.2 d, 1: 20.5 d |

→ often cooked recipes (favorites) come back **faster** than rarely cooked ones.

**Edge cases**

| Case | Handling |
|---|---|
| never cooked (no `last_date`) | `date_score = 5`, not removed |
| cooked within 4 days (`dist_last ≤ 4`) | `date_score ≤ 0` → `remove = True` |
| ≤ 1 date (also 0 dates + `last_date` from "cooked once") | `factor = 1` |
| empty `repeat_rating` | `repeat = 2` |

## 2. `reward_score()` → reward_score ✅ 🧪

```
time      = cook_minutes + prep_minutes
timescore = 1 / (1 + exp((time - 50) / 7.5))      # 7.5 min as unit
            → 50 min = 0.5, 40 min ≈ 0.8

taste  = mean(taste_rating)                       # 0 = bad, 10 = great
effort = mean(effort_rating)                      # 1 = low, 5 = high

taste_part  = (taste / 10) ^ 1.5                  # low taste is punished hard
cost        = (effort - 1) / 4                    # 0 = low, 1 = high
effort_part = 1 - 0.5 · (taste / 10) · cost       # effort counts more for tasty dishes

reward = 10 · timescore · taste_part · effort_part     ∈ [0, 10]
```

The same-day filter (`cook_minutes` or `prep_minutes` > 60 → remove) is a hard filter, see II.4.

Idea:
- effort is a **penalty** (multiplied), not added.
- bad taste can't be saved by low effort: taste 2 + effort 1 = 0.88 < taste 10 + effort 5 = 4.91.
- effort effect grows with taste: taste 2 → max. −10 %, taste 10 → max. −50 %.

Tuning knobs in `ProposeLogic.py`: `COOK_MID` (50), `COOK_UNIT` (7.5), `TASTE_EXP` (1.5), `EFFORT_WEIGHT` (0.5).

**Ranges**

| time (min) | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 90 |
|---|---|---|---|---|---|---|---|---|
| timescore | 0.99 | 0.98 | 0.94 | 0.79 | 0.50 | 0.21 | 0.07 | 0.01 |

reward at 20 min (rows: taste 0–10, columns: effort 1–5):

| taste \ effort | 1 | 2 | 3 | 4 | 5 | effort loss |
|---|---|---|---|---|---|---|
| 10 | 9.82 | 8.59 | 7.37 | 6.14 | 4.91 | 50 % |
| 8 | 7.03 | 6.32 | 5.62 | 4.92 | 4.22 | 40 % |
| 6 | 4.56 | 4.22 | 3.88 | 3.54 | 3.19 | 30 % |
| 4 | 2.48 | 2.36 | 2.24 | 2.11 | 1.99 | 20 % |
| 2 | 0.88 | 0.86 | 0.83 | 0.81 | 0.79 | 10 % |
| 0 | 0 | 0 | 0 | 0 | 0 | – |

**Edge cases**

| Case | Handling |
|---|---|
| never cooked (no ratings) | `taste = 8`, `effort = 3`, `time = 45 min` → reward ≈ 3.8 |
| missing times | treat as 45 min |
| total time > 60 min (each part < 60) | passes the filter, timescore → reward ≈ 0 |

✅ **Rating UI** ([Server/rating.html](../Server/rating.html)): taste 0–10, effort "1 = sehr einfach, 5 = sehr aufwendig". Existing data converted (taste × 2, effort 6 − x).

## 3. `calc_damping()` → damp_score_mult, damp_score_offset (with `last_supper()`) ✅ 🧪 ❓ (VIII.10, VIII.11)

```
load the last 3 cooked meals → last_supper (array[ids])
ignore if longer than 4 days ago
load ingredients from recipe_ingredients for last_supper

build ONE merged list from all last_supper meals (once, before the loop):
  ls_origins = all origins
  ls_methods = all cooking methods
  ls_specs   = only sweet, soup, casserole (no other specs)
  ls_sides   = all side_dish ingredients
  ls_mains   = all main ingredients
  ls_meats   = [incredient for incredient if veg_type==meat]

Loop recipe candidates:
  init damp_score_mult   = 1
  init damp_score_offset = 0
  If season overlap (current season, "all" also)     offset + 3
  If candidate origin in ls_origins                  offset - 1
  If candidate cooking method in ls_methods          nothing
  If candidate sweet, soup or casserole in ls_specs  mult · (1 - 0.8)
  If candidate side_dish in ls_sides                 offset - 3
  If candidate is meat                               mult · (1 - 0.1 · len(ls_meats))
    - Note: (1-x)^n >= 1-nx
  If candidate meat in ls_meats                      offset - 5
  If candidate main ingredient exists:
    If main ingredient in ls_mains:
      If main ingredient == meat or side_dish        mult · (1 - 0.1)
      else                                           offset - 3

→ every rule only checks "in list: yes / no" → fires at most once per candidate
```

**Ranges**

| Value | Range | Note |
|---|---|---|
| `damp_score_mult` | ≈ 0.13 – 1 | worst case: sweet/soup/casserole ×0.2, meat ×0.7 (3 meat types), main ×0.9 |
| `damp_score_offset` | −12 – +3 | origin −1, side −3, same meat −5, main −3, season +3 |

❓ Note: a negative offset might be too strong (VIII.10).

## 4. `hard_filter()` → allowed recipes ✅ 🧪

```
remove == True from date_score      → remove   (already removes last_supper itself)
load all variants of last_supper (recipe field variant_of)
                                    → remove variants and original of last_supper
blacklist (blacklist.yaml of the user + optional extra set) → remove
wrong recipe_type / veg_type        → remove   (diet: vegetarian also allows vegan, nonvegan = not vegan)
cook_minutes or prep_minutes > 60   → remove   (same-day cooking; exactly 60 is ok)
include: not ALL ingredients in it  → remove   (ingredient name, case-insensitive, or ingredient_id)
exclude: ANY ingredient in it       → remove
allergies (lactose, gluten, …)      → remove if an ingredient has <allergy>_free == false
                                               (field missing = unknown → not filtered)
```

Server: `GET /api/propsals?user=<id>` → `propose()` with 5 results. `POST /api/propsals` takes
`meal_type, diet, include, exclude, allergies, user_id, count` (default 10: shown + buffer for dismissing).

Runs **after** date_score (I.3), because `remove` comes from date_score.

# III. Generation List – `calc_total_score()` ✅ 🧪

> Uses: date_score | reward_score | damp_score | wishlist

```
wishlist_score =10 if on wishlist else 0

score = (date_score + reward_score + wishlist_score) · damp_score_mult + damp_score_offset+wishlist_score/5

p_i = exp(score_i / T) / Σ_j exp(score_j / T)          # softmax over all remaining recipes
```

Tuning knobs in `ProposeLogic.py`: `WISHLIST_SCORE` (10), `WISHLIST_UNDAMPED` (5 → +2), `SOFTMAX_T` (T, currently 3). Small T → the best recipes almost always win, large T → more random.
Negative scores need no clamp: `exp` is always > 0.

**Ranges**

| Part | Range |
|---|---|
| date_score | 0 – 10 |
| reward_score | 0 – 10 |
| wishlist_score | 0 or 10 (+2 undamped) |
| before damping | 0 – 30 |
| after damping (+ wishlist/5) | ≈ −12 – 35 |

**Drawing** – `softmax()`, `draw_proposals()` ✅ 🧪

```
repeat 5 times:
    softmax over the recipes still in the container
    draw 1 recipe (draw without putting back)
    remove the drawn recipe AND its variants from the container
```

**Swapping out recipes** – `swap_proposals()` ✅ 🧪

- X: meal is proposed ("proposed")
- ¬X: meal is never cooked ("never cooked")
- Y = number of X with n = 5 tries, Y ~ Bin(5, p)
- **Given:** P(Y = 5) = p⁵ = 0.8 → p ≈ 0.956
- P(¬X) = 1 − p ≈ 0.044 = w

For each proposal: swap with probability 1 − p. Skip if on wishlist.
→ in 20 % of all lists at least one recipe gets swapped.

💡 Swap candidates: never cooked recipes first, then random from the rest (excluding last_supper, its variants and recipes already in the list).

# IV. Measured Variables

Per recipe there is exactly **one** history entry. The arrays inside rotate (max. 20 values, see `RatingLogic.HISTORY_ARRAY_MAX`).

| Field | Source | Type | Meaning | Default / missing |
|---|---|---|---|---|
| `dates` | history | list ISO date | days when rated (cooked) | `[]` |
| `last_date` | history | ISO date | last cooked (also via "cooked once") | missing → never cooked |
| `repeat_rating` | history | list int 1–5 | desire to repeat | `2` (II.1); seed for uncooked recipes: `[1]` |
| `taste_rating` | history | list int **0–10** | taste (0 = bad, 10 = great) | `8` (II.2), UI prefill `5` |
| `effort_rating` | history | list int 1–5 | effort (1 = low, **5 = high effort**) | `3` |
| `prep_minutes` / `cook_minutes` | recipe | int | times | 45 min total (II.2) |
| `season` | recipe | str | season | `all` |
| `variant_of` | recipe | id / null | original recipe of a variant | `null` |
| `sweet` | recipe | bool | sweet dish | `false` |
| `veg_type` | recipe | str | vegan / vegetarian / meat | – |
| `origin` | recipe | list str | cuisine (II.3) | `[]` |
| `cooking_method` | recipe | str | oven, pan, … (II.3) | `null` |
| `recipe_spec` | recipe | str | soup, casserole, … (II.3) | `null` |
| `main_ingredient` | recipe | `ingredient_id` / "not specific" | compared with the meat / side ingredients (II.3) | `null` |
| type of meat | ingredients with `veg_type = meat` | `ingredient_id` | chicken, beef, … (II.3 `ls_meats`) | ❓ VIII.11 |
| `side_dish` | ingredient | bool | ingredient is a side (rice, noodles, …) | `false` |
| wishlist | wishlist | recipe_id, user_id | "put on next" | – |
| blacklist | 💡 new, like wishlist | recipe_id, user_id | user doesn't like it at all | – |

# V. Database Structure

## Recipes – fields + `YamlEditor.data_problems()` ✅ 🧪

- **Season:** all, spring, summer, autumn, winter
- **Recipe type:** main dish, dessert, dip, spice mix, side dish, snack, starter
- **Recipe specs:** soup, salad, casserole, bowl, sandwich, others
  - 💡 keep it one value per recipe, so damping (II.3) stays simple
- **Cooking method:** oven, pan, pot, grill, raw, steam
- **Origin:** asian, oriental, mexican, indian, italian, home-style, mediterranean, american (can have multiple)
- **Main ingredient** (if not specified): only check on creation whether the title matches the ingredients
  - can also be set to "not specific"
- **Variants:** if a recipe is saved with noodles, a variant can be the same with rice, for example.
  When creating a recipe and choosing rice as an ingredient (saved as side dish), there can be an option to automatically create variants for other choices (noodles etc.).

## Ingredients – `lactose_free`, `gluten_free` ✅ 🧪

`ingredient_id, name, unit, veg_type, lactose_free, gluten_free, specs_ingredient`

- **lactose_free / gluten_free:** `true` / `false` / `null` (= unknown, doesn't filter). Set in the ingredient forms.

- **specs_ingredient:** side_dish, spice, basics (e.g. water, flour, butter, oil, …)

## Blacklist – filter ✅ 🧪 · button / endpoint to add entries ⬜

`server_data/blacklist.yaml`, same structure as `wishlist.yaml`: `recipe_id, user_id, date`.
Read by `propose()` (`user_blacklist`). There is no button / endpoint to add entries yet.

# VI. Old Formula (removed)

Until 2026-09-28 the app used `repeatScore` with `date_score = 10 · repeat/5 · exp(−8 · s / d_last)`.
It failed the sanity checks (cooked today → 8.0, cooked every 3 days → 10.0) and was replaced by II.1 (tanh).
See git history for details.

# VII. Sanity Checks

Expected behavior of the app code. Every row matches a check in the test (IX).

| Situation | Expected | II.1 tanh |
|---|---|---|
| just cooked | removed / 0 | ✅ 0, removed |
| cooked within 4 days (incl. exactly 4) | removed | ✅ removed |
| 5 days ago | not removed | ✅ |
| cooked rarely, long ago | high (~2·repeat) | ✅ 9.94 |
| normal rhythm, in between | medium | ✅ 5.18 |
| never cooked | medium | ✅ 5.00 |
| higher repeat ⇒ higher score | monotonically increasing | ✅ |
| longer ago ⇒ higher score | monotonically increasing | ✅ |
| always in [0, 10] | – | ✅ |

| Situation | Expected | II.2 / II.3 / III |
|---|---|---|
| quick & tasty & low effort | reward ≈ 10 | ✅ 9.82 (20 min, taste 10, effort 1) |
| taste 0 | reward 0 | ✅ |
| 50 min, otherwise perfect | reward halved | ✅ |
| bad taste + low effort vs. great taste + high effort | great taste wins | ✅ 0.88 < 4.91 |
| higher taste ⇒ higher reward | monotonically increasing | ✅ |
| more effort ⇒ lower reward | monotonically decreasing | ✅ |
| effort effect bad vs. tasty dish | smaller for bad dish | ✅ −10 % vs. −50 % |
| same meat + side + main as yesterday | strongly damped, but still positive | ✅ 3.72 at base 12 |
| other meat type than last_supper | only ×(1 − 0.1·n), no −5 | ✅ |
| same main, neither meat nor side | −3 | ✅ |
| soup after soup | strongly damped | ✅ ×0.2 |
| nothing in common with last_supper | unchanged (+ season) | ✅ |
| every damping rule | fires max. once | ✅ |
| negative score | still drawable, but rarely | ✅ 9.4 % at T = 3 |
| higher score ⇒ higher probability | monotonically increasing | ✅ |
| recipe and its variant in the same list | never | ✅ 0 of 10 000 |
| at least one swap in a list | 20 % | ✅ 20.0 % |

# VIII. Open Questions

1. ~~**II.1 direction of exp**~~ → replaced by tanh.
2. ❓ **II.1 factor:** favorites (factor 4) come back after ~8 days, rarely cooked (factor 1) after ~20 days. Recipes cooked only once → factor 1 → slow. Intended?
3. ~~**II.1 "without today"**~~ → without today.
4. ~~**`repeat_rating` mean or last value**~~ → mean (II.1).
5. ~~**II.2 effort**~~ → multiplicative formula, UI + data fixed.
6. ~~**II.3 count rules once per candidate**~~ → merged last_supper list. Chicken hitting 3 rules (meat in last_supper, same meat, main = chicken) is intended.
7. ~~**II.3 season**~~ → bonus +3, inside the candidate loop after init.
8. ~~**III negative scores**~~ → softmax, no clamp needed.
9. ~~**II.1 factor with ≤ 1 date**~~ → `factor = 1`.
10. ❓ **II.3:** is the negative offset too strong? (tune in `ProposeLogic.py`, check with the test)
11. ❓ **II.3 type of meat:** app currently uses the ingredients with `veg_type = meat` (`recipe_features`). Keep that, or a new recipe field?
12. ~~**III wishlist damped?**~~ → wishlist 10 is damped, but `wishlist_score/5` (+2) is added undamped after damping.

# IX. Logic Test (example scenarios for the app code)

Test script [tests/test_propose_plan.py](../tests/test_propose_plan.py): imports `Tools/ProposeLogic.py` and feeds it example scenarios
(history entries with dates, damping cases, a small fake recipe database). The server does **not** need to run.
It contains no formulas itself – tune the knobs in `ProposeLogic.py` and re-run.

```
python tests/test_propose_plan.py              # prints all tables + sanity checks (63/63 passed)
python -m pytest tests/test_propose_plan.py    # only the sanity checks (needs pytest)
```

## IX.1 date_score

| Case | factor | date_score | removed |
|---|---|---|---|
| never cooked | – | 5.00 | – |
| cooked today, once, r=4 | 1 | 0.00 | ✅ |
| once, 7 days ago, r=3 | 1 | 0.60 | – |
| every 3 days, last 3 ago, r=5 | 3.79 | 0.00 | ✅ |
| every 7 days, last exactly 4 ago, r=5 | 3.50 | 0.00 | ✅ |
| every 7 days, last 7 ago, r=5 | 3.50 | 3.36 | – |
| every 7 days, last 14 ago, r=5 | 3.50 | 8.23 | – |
| every 20 days, last 13 ago, r=4 | 2.57 | 5.18 | – |
| every 20 days, last 40 ago, r=4 | 2.57 | 7.97 | – |
| every 90 days, last 90 ago, r=5 | 1 | 9.94 | – |
| every 90 days, last 10 ago, r=5 | 1 | 1.97 | – |

## IX.2 reward_score

Taste 0–10, effort 1 = low, 5 = high. Full grid see II.2.

## IX.3 damping

last_supper = chicken curry (indian, rice, chicken), pumpkin soup (autumn, soup, pumpkin), chicken wok (asian, rice, chicken).
Current season = autumn. Base score = 12 (e.g. date 5 + reward 7).

| Candidate | mult | offset | score | Rules hit |
|---|---|---|---|---|
| Butter chicken | 0.81 | −6 | 3.72 | season, origin, side, meat ×0.9 (1 meat type), same meat −5, main = meat ×0.9 |
| Tomato soup | 0.20 | +3 | 5.40 | season, sweet/soup/casserole ×0.2 |
| Veggie pasta | 1.00 | +3 | 15.00 | season |
| Summer salad | 1.00 | 0 | 12.00 | – (out of season) |
| Beef burger | 0.90 | +3 | 13.80 | season, meat ×0.9 (other meat type → no −5) |
| Pumpkin curry | 1.00 | −4 | 8.00 | season, origin, side, main = pumpkin again (neither meat nor side) −3 |

## IX.4 Drawing & swapping (10 000 runs)

Softmax, 5 draws without putting back, variants removed after a draw. Small example pool (7 recipes for 5 slots) → differences look compressed.

| Recipe (score) | T = 1 | **T = 3** | T = 5 | T = 10 |
|---|---|---|---|---|
| A (20) | 50.0 % | 50.2 % | 50.1 % | 49.4 % |
| A-rice variant (20) | 50.0 % | 49.8 % | 49.9 % | 50.5 % |
| B (10) | 100 % | 99.8 % | 97.1 % | 87.6 % |
| G (8) | 100 % | 98.6 % | 93.3 % | 82.2 % |
| C (5) | 99.9 % | 90.9 % | 81.4 % | 73.0 % |
| D (2) | 81.9 % | 62.3 % | 60.4 % | 61.7 % |
| E (0.5) | 18.0 % | 38.9 % | 46.7 % | 56.1 % |
| F (−4) | 0.2 % | 9.4 % | 21.1 % | 39.5 % |

- A and its variant together: **0** ✅
- Swap: p = 0.9564, per slot 4.36 %, P(≥ 1 swap in 5) = **20.0 %** ✅

## IX.5 Full pipeline `propose()` (example database, 3000 runs)

today = 2026-09-28 (autumn). Chicken curry cooked yesterday, pumpkin soup 2 days ago → last_supper. Blacklist = Liver, wishlist = Pumpkin risotto.

| Recipe | date | reward | mult | offset | score | in list | why |
|---|---|---|---|---|---|---|---|
| Chicken curry | 0.00 | 5.10 | 0.81 | −6 | −1.87 | 0 % | cooked yesterday → remove |
| Pumpkin soup | 0.00 | 4.71 | 0.20 | 0 | 0.94 | 0 % | cooked 2 days ago → remove |
| Chicken curry (noodles) | 5.00 | 4.53 | 0.81 | −3 | 4.72 | 0 % | variant of last_supper |
| Butter chicken | 9.77 | 4.37 | 0.81 | −6 | 5.46 | 70.7 % | same chicken + rice → damped |
| Veggie pasta | 6.00 | 4.49 | 1.00 | +3 | 13.49 | 95.7 % | |
| Beef burger | 5.00 | 5.35 | 0.90 | +3 | 12.32 | 95.7 % | never cooked |
| Tomato soup | 3.31 | 3.10 | 0.20 | +3 | 4.28 | 53.6 % | soup after soup ×0.2 |
| Lasagne | 5.00 | 0.00 | 0.90 | +3 | 7.50 | 0 % | prep 70 min → same-day filter (> 60) |
| Pad thai | 5.00 | 5.35 | 0.90 | −2 | 7.32 | 84.3 % | chicken again −5 |
| Pumpkin risotto | 5.00 | 4.53 | 1.00 | −3 | 18.53 | 100 % | wishlist |
| Liver | 1.99 | 0.86 | 0.90 | +3 | 5.56 | 0 % | blacklist |
| Pancakes | 5.00 | 5.62 | 1.00 | +3 | 13.62 | 0 % | dessert → wrong type |

## Changelog

- 2026-09-23 – Draft created, `date_score` (old formula) implemented and documented.
- 2026-09-27 – New plan (II–V) added, cleaned up; old formula moved to VI.
- 2026-09-27 – Translated to English, suggestions (💡) added for filter list, recipe specs and more.
- 2026-09-27 – Reward + damping rules added by user; reviewed step by step, hard filters, ranges, edge cases and blacklist added; logic test (IX) added.
- 2026-09-27 – II.2 reward: effort is now a taste-scaled penalty (effort 5 = high effort); test moved to `tests/test_propose_plan.py`.
- 2026-09-28 – II.1 tanh formula (user) tested; taste scale 0–10, reward 0–10; rating UI + data fixed (taste 0–10, effort 5 = high).
- 2026-09-28 – II.3 merged last_supper list, meat types, main-ingredient rule; hard filter after date_score; `remove` at date_score ≤ 0; softmax in III. Doc + test (29/29) brought up to date.
- 2026-09-28 – Formulas moved from the test into `Tools/ProposeLogic.py` (old `repeatScore` removed); test now only feeds example scenarios (41/41). Status table shows app implementation.
- 2026-10-07 – Server connected: `/api/propsals` (GET + POST) now runs `propose()`. Same-day filter changed to > 60 min (user decision). Hard filter extended: include/exclude ingredients, allergies (`<allergy>_free == false`), diet mapping (vegetarian ⊇ vegan, nonvegan), per-user `blacklist.yaml`. `propose(k=…)` for the frontend buffer. Test 57/57 incl. server endpoints via Flask test client.
- 2026-10-07 – Recipe fields `origin`, `cooking_method`, `recipe_spec`, `main_ingredient` and ingredient fields `lactose_free`, `gluten_free` added (data, `YamlEditor`, creation + ingredients pages). Allowed values in `YamlEditor` (+ `pot`, `american`), checked by `YamlEditor.data_problems`. Test 63/63, incl. checks on the real data.
