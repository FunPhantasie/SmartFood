# Propose Logic – Formulas

Every formula is written down here as planned, so code and idea can be checked against each other later.

> **Code lives only in the test notebooks** ([docs/Testing/](Testing/)) – this file only describes the concept (formulas, rules), no code and no results.
> Fine tuning (constants, ranges, example results) happens in the notebooks. Each section links its notebook.
>
> **Status** – shown next to every function heading. **Reset 2026-10-11: everything is ⬜ not implemented · 🟠 not tested** until checked again in the notebooks.
>
> ⬜ not implemented · ✅ implemented in logic · ❌ logic error · ❓ open question (VIII) · 🟠 not tested · 🧪 tested in notebook
>
> 💡 = suggestion, not decided yet · ⚠️ = found by a notebook test
>
> Old implementation (not trusted until re-tested): [Tools/ProposeLogic.py](../Tools/ProposeLogic.py), [tests/test_propose_plan.py](../tests/test_propose_plan.py).
> Currently Working At Implementing Logic test Cases import Recipes
---

# I. Overview – `propose()`, `build_propose_dataset()` ⬜ 🟠

Notebook: [Testing/test_with_data.ipynb](Testing/test_with_data.ipynb) (empty)

1. Load all data (could be inefficient)
   1. Recipes
   2. History
   3. Recipe ingredients
   4. Wishlist
   5. Blacklisted recipes (user doesn't like them at all)
2. From history calculate **date_score** (II.1)
   - mean / std of the gaps in `dates` (last 20)
   - distance last cooked ↔ today: `last_date` (date)
   - repeat score: `repeat_rating` (array[int], 0–10)
   - rotation point `M` from all recipes + app usage
   - sets `remove = True` if cooked within the last 5 days
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

## 1. `date_score()` → date_score, remove ⬜ 🧪

Notebook: [Testing/date_score.ipynb](Testing/date_score.ipynb)

Idea: every recipe has its own rhythm. It should come back close to its **mean** gap, so the **std** of its gaps gets small.
The Wdh rating decides a small shift of that target towards earlier (liked) or later (not liked).

| Variable | Meaning |
|---|---|
| `dates` | last 20 days the recipe was cooked (rated **or** "Einmal gekocht"), same day counts once |
| `dist_last` | days between `last_date` and today |
| `mean`, `std` | mean / std of the gaps between `dates` |
| `repeat` | mean of `repeat_rating` (0–10, 5 = neutral) |
| `n_rotation` | number of recipes with ≥ 2 `dates` |
| `usage_every` | 30 days / number of cooks (all recipes) in the last 30 days |
| `M` | rotation point: `n_rotation · usage_every` |

**Rotation point** – e.g. app used 10× a month → every 3 days; 10 recipes in rotation → `M` = 30 days

$$
M = n\_rotation \cdot usage\_every
$$

**Shift** – tanh with Wdh 5 in the center: 5 = no shift, 10 → earlier, 0 → later

$$
w = \tanh\left(\frac{5 - repeat}{k_r}\right) \in (-1, 1), \qquad T = mean + w \cdot |M - mean|
$$

**Amplification** – the curve reaches 90 % of max exactly at `T`, clipped to [1, 4]

$$
amp = \text{clip}\left(\frac{\tau \cdot \operatorname{artanh}(0.9)}{T - b},\; 1,\; 4\right), \qquad \tau = \frac{60 - b}{\operatorname{artanh}(0.8)}
$$

`amp = 1` → 80 % after 60 days (slowest), `amp = 4` → fastest. Because of the clip, 90 % is reached between `T_min` and `T_max`, never earlier / later.

**Result**

$$
\text{date\_score} = \max\left(0,\; 10 \cdot \tanh\left(\frac{amp}{\tau} \cdot (dist\_last - b)\right)\right) \in [0, 10], \qquad b = \text{nulldurchgang} = 5
$$

## Flow

1. Never cooked (`last_date` missing) → `date_score = 5`, not removed.
2. `mean`, `std` from the last 20 `dates`. < 2 dates → `mean = M` (so `T = M`).
3. `repeat` = mean of `repeat_rating`, without ratings = 5 (no shift).
4. `T`, `amp`, `date_score` as above.
5. raw score ≤ 0 (cooked within `b` days) → `0`, removed.

Knobs (`b`, `k_r`, 90 %, [1, 4], 30-day window) are tuned in the notebook.

❓ `std` is only computed and shown so far (it is the thing the logic tries to make small) – it is not used inside the formula.
❓ The shift is `|M − mean|`, so it can be large (rarely cooked, Wdh 9 → `T` jumps from 60 to ~20 days). Cap it?

## 2. `reward_score()` → reward_score ⬜ 🟠

Notebook: [Testing/reward_score.ipynb](Testing/reward_score.ipynb)

| Variable | Meaning |
|---|---|
| `time` | `cook_minutes + prep_minutes` |
| `taste` | mean of `taste_rating` (0 = bad, 10 = great) |
| `effort` | mean of `effort_rating` (1 = low, 5 = high) |

**Time** – 50 min = midpoint (0.5), 7.5 min as unit

$$
\text{timescore} = \frac{1}{1 + e^{(time - 50)/7.5}}
$$

**Taste** – low taste is punished hard

$$
\text{taste\_part} = \left(\frac{taste}{10}\right)^{1.5}
$$

**Effort** – cost 0 = low, 1 = high; effort counts more for tasty dishes

$$
\text{cost} = \frac{effort - 1}{4}, \qquad \text{effort\_part} = 1 - 0.5 \cdot \frac{taste}{10} \cdot \text{cost}
$$

**Result**

$$
\text{reward} = 10 \cdot \text{timescore} \cdot \text{taste\_part} \cdot \text{effort\_part} \in [0, 10]
$$

The same-day filter (`cook_minutes` or `prep_minutes` > 60 → remove) is a hard filter, see II.4.

Idea:
- effort is a **penalty** (multiplied), not added.
- bad taste can't be saved by low effort.
- effort effect grows with taste: max. penalty = 50 % · taste / 10.

**Edge cases**

| Case | Handling |
|---|---|
| never cooked (no ratings) | `taste = 8`, `effort = 3`, `time = 45 min` |
| missing times | treat as 45 min |
| total time > 60 min (each part < 60) | passes the filter, but timescore makes the reward small |

⬜ 🟠 **Rating UI** ([Server/rating.html](../Server/rating.html)): taste 0–10, effort "1 = sehr einfach, 5 = sehr aufwendig". Existing data converted (taste × 2, effort 6 − x).

## 3. `calc_damping()` → damp_score_mult, damp_score_offset (with `last_supper()`) ⬜ 🟠 ❓ (VIII.10, VIII.11)

Notebook: [Testing/damping.ipynb](Testing/damping.ipynb)

**last_supper** = the last 3 cooked meals, ignored if cooked more than 4 days ago. Their ingredients come from `recipe_ingredients`.

Build **one** merged list from all last_supper meals (once, before looping the candidates):

| List | Content |
|---|---|
| `ls_origins` | all origins |
| `ls_methods` | all cooking methods |
| `ls_specs` | only sweet, soup, casserole (no other specs) |
| `ls_sides` | all side_dish ingredients |
| `ls_mains` | all main ingredients |
| `ls_meats` | all ingredients with `veg_type == meat` (each one counts for `len`) |

**Rules per candidate** – start with `damp_score_mult = 1`, `damp_score_offset = 0`:

| Condition | Effect |
|---|---|
| season overlap (current season, "all" also) | offset + 3 |
| candidate origin in `ls_origins` | offset − 1 |
| candidate cooking method in `ls_methods` | nothing |
| candidate sweet, soup or casserole in `ls_specs` | mult · (1 − 0.8) |
| candidate side_dish in `ls_sides` | offset − 3 |
| candidate is meat | mult · (1 − 0.1 · len(`ls_meats`)) — note: (1−x)ⁿ ≥ 1−nx |
| candidate meat in `ls_meats` | offset − 5 |
| main ingredient in `ls_mains` and it is meat or side_dish | mult · (1 − 0.1) |
| main ingredient in `ls_mains`, otherwise | offset − 3 |

→ every rule only checks "in list: yes / no" → fires at most once per candidate.

❓ Note: a negative offset might be too strong (VIII.10).

## 4. `hard_filter()` → allowed recipes ⬜ 🟠

Notebook: none yet

A recipe is **removed** if:

| Condition | Note |
|---|---|
| `remove == True` from date_score | already removes last_supper itself |
| it is a variant or the original of a last_supper recipe | via recipe field `variant_of` |
| on the blacklist | `blacklist.yaml` of the user + optional extra set |
| wrong `recipe_type` / `veg_type` | diet: vegetarian also allows vegan, nonvegan = not vegan |
| `cook_minutes` or `prep_minutes` > 60 | same-day cooking; exactly 60 is ok |
| include: not ALL ingredients in it | ingredient name (case-insensitive) or `ingredient_id` |
| exclude: ANY ingredient in it | |
| allergies (lactose, gluten, …): an ingredient has `<allergy>_free == false` | field missing = unknown → not filtered |

Server: `GET /api/propsals?user=<id>` → `propose()` with 5 results. `POST /api/propsals` takes
`meal_type, diet, include, exclude, allergies, user_id, count` (default 10: shown + buffer for dismissing).

Runs **after** date_score (I.3), because `remove` comes from date_score.

# III. Generation List – `calc_total_score()` ⬜ 🟠

Notebook: [Testing/total_score.ipynb](Testing/total_score.ipynb)

> Uses: date_score | reward_score | damp_score | wishlist

`wishlist_score` = 10 if on wishlist, else 0.

$$
\text{score} = (\text{date\_score} + \text{reward\_score} + \text{wishlist\_score}) \cdot \text{damp\_score\_mult} + \text{damp\_score\_offset} + \frac{\text{wishlist\_score}}{5}
$$

Softmax over all remaining recipes:

$$
p_i = \frac{e^{score_i / T}}{\sum_j e^{score_j / T}}
$$

Small T → the best recipes almost always win, large T → more random.
Negative scores need no clamp: `exp` is always > 0.

**Drawing** – `softmax()`, `draw_proposals()` ⬜ 🟠 (notebook: [Testing/total_score.ipynb](Testing/total_score.ipynb), single draw only)

Repeat 5 times:
1. softmax over the recipes still in the container
2. draw 1 recipe (draw without putting back)
3. remove the drawn recipe AND its variants from the container

**Swapping out recipes** – `swap_proposals()` ⬜ 🟠 (notebook: none yet)

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
| `dates` | history | list ISO date | days when cooked (rated or "cooked once"), last 20 | `[]` |
| `last_date` | history | ISO date | last cooked (also via "cooked once") | missing → never cooked |
| `repeat_rating` | history | list int **0–10** | desire to repeat (5 = neutral) | `5` (II.1), UI prefill `5`; dismiss / seed for uncooked recipes: `0` |
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

## Recipes – fields + `YamlEditor.data_problems()` ⬜ 🟠

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

## Ingredients – `lactose_free`, `gluten_free` ⬜ 🟠

`ingredient_id, name, unit, veg_type, lactose_free, gluten_free, specs_ingredient`

- **lactose_free / gluten_free:** `true` / `false` / `null` (= unknown, doesn't filter). Set in the ingredient forms.

- **specs_ingredient:** side_dish, spice, basics (e.g. water, flour, butter, oil, …)

## Blacklist – filter ⬜ 🟠 · button / endpoint to add entries ⬜ 🟠

`server_data/blacklist.yaml`, same structure as `wishlist.yaml`: `recipe_id, user_id, date`.
Read by `propose()` (`user_blacklist`). There is no button / endpoint to add entries yet.

# VI. Old Formula (removed)

Until 2026-09-28 the app used `repeatScore` with `date_score = 10 · repeat/5 · exp(−8 · s / d_last)`.
It failed the sanity checks (cooked today → 8.0, cooked every 3 days → 10.0) and was replaced by II.1 (tanh).
See git history for details.

# VII. Sanity Checks → moved to the notebooks

The sanity checks now live at the end of each notebook (cell "Sanity Checks"):

- II.1 date_score → [Testing/date_score.ipynb](Testing/date_score.ipynb)
- II.2 reward_score → [Testing/reward_score.ipynb](Testing/reward_score.ipynb)
- II.3 damping → [Testing/damping.ipynb](Testing/damping.ipynb)
- III total score, drawing, swapping → [Testing/total_score.ipynb](Testing/total_score.ipynb)

# VIII. Open Questions

1. ~~**II.1 direction of exp**~~ → replaced by tanh.
2. ~~**II.1 factor**~~ → replaced by mean/std of the gaps + rotation point `M` + Wdh shift (2026-10-13).
3. ~~**II.1 "without today"**~~ → without today.
4. ~~**`repeat_rating` mean or last value**~~ → mean (II.1).
5. ~~**II.2 effort**~~ → multiplicative formula, UI + data fixed.
6. ~~**II.3 count rules once per candidate**~~ → merged last_supper list. Chicken hitting 3 rules (meat in last_supper, same meat, main = chicken) is intended.
7. ~~**II.3 season**~~ → bonus +3, inside the candidate loop after init.
8. ~~**III negative scores**~~ → softmax, no clamp needed.
9. ~~**II.1 factor with ≤ 1 date**~~ → `factor = 1`.
10. ❓ **II.3:** is the negative offset too strong? (tune in [Testing/damping.ipynb](Testing/damping.ipynb))
11. ❓ **II.3 type of meat:** app currently uses the ingredients with `veg_type = meat` (`recipe_features`). Keep that, or a new recipe field?
12. ~~**III wishlist damped?**~~ → wishlist 10 is damped, but `wishlist_score/5` (+2) is added undamped after damping.

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
- 2026-10-11 – Code removed from this doc, it now lives only in the notebooks in `docs/Testing/` (linked per section). Logic kept as formulas / rule tables. All statuses reset to ⬜ not implemented · 🟠 not tested; old test values marked "old".
- 2026-10-11 – Sanity checks (VII) moved into the notebooks in `docs/Testing/`.
- 2026-10-11 – Concept only: ranges, result tables, tuning knobs and the logic test (IX) removed; fine tuning happens in the notebooks.
- 2026-10-13 – II.1 new logic (user): target `T` = mean gap + Wdh-weighted shift towards / away from the rotation point `M`, tanh reaches 90 % at `T` (amp clipped to [1, 4]). Notebook rewritten, sanity checks 15/15. `repeat_rating` now 0–10 (UI, `RatingLogic`, data: old `(x − 1) · 2.5`). "Einmal gekocht" now also adds to `dates` (other arrays get `None`), so `dates` holds every cook (last 20).
