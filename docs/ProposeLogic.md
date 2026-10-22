# Propose Logic – Overview

This file is only the **overview**: what happens in which order and where it is defined.

> **Formulas, derivations, plots, sanity checks and edge cases live in the notebooks** ([docs/Testing/](Testing/)) – one per score, linked below.
> The app implements exactly these formulas in [Tools/ProposeLogic.py](../Tools/ProposeLogic.py). Each notebook checks itself against that code (`notebook == backend`).
> Backend logic test: [tests/test_propose_plan.py](../tests/test_propose_plan.py) · real data step by step: [Testing/test_with_data.ipynb](Testing/test_with_data.ipynb)
>
> **Status** – shown next to every step:
> ⬜ not implemented · ✅ implemented in logic · ❌ logic error · ❓ open question (VIII) · 🟠 not tested · 🧪 tested (notebook / test)
>
> 💡 = suggestion, not decided yet · ⚠️ = found by a notebook test
---

# I. Overview Workflow

## 1. Load all data
- Recipes, history, recipe ingredients, ingredients, wishlist, blacklist (user doesn't like them at all)

## 2. Scores per recipe
| Score | From | Notebook | Status |
|---|---|---|---|
| **date_score**, `remove` | history (`dates`, `last_date`, `repeat_rating`) + app usage | [date_score.ipynb](Testing/date_score.ipynb) | ✅ 🧪 |
| **reward_score** | history (`taste_rating`, `effort_rating`) + recipe times | [reward_score.ipynb](Testing/reward_score.ipynb) | ✅ 🧪 |
| **damping** (`mult`, `offset`) | similarity to the last 3 meals (last_supper) | [damping.ipynb](Testing/damping.ipynb) | ✅ 🧪 |
| **total score** | all of the above + wishlist | [total_score.ipynb](Testing/total_score.ipynb) | ✅ 🧪 |

## 3. Hard filter – `hard_filter()` ✅ 🧪
Notebook: none (rules only, checked in the backend test). A recipe is **removed** if:

| Condition | Note |
|---|---|
| `remove == True` from date_score (cooked ≤ 5 days ago) | the **wishlist overrides** this |
| it is a variant or the original of a last_supper recipe | via recipe field `variant_of` |
| on the blacklist | `blacklist.yaml` of the user + optional extra set – wins over the wishlist |
| wrong `recipe_type` / `veg_type` | diet: vegetarian also allows vegan, nonvegan = not vegan |
| `cook_minutes` or `prep_minutes` > 60 | same-day cooking; exactly 60 is ok |
| include: not ALL ingredients in it | ingredient name (case-insensitive) or `ingredient_id` |
| exclude: ANY ingredient in it | |
| allergies (lactose, gluten, …): an ingredient has `<allergy>_free == false` | field missing = unknown → not filtered |

Runs **after** date_score, because `remove` comes from date_score.

## 4. Two pools ✅ 🧪
| Pool | Recipes |
|---|---|
| **main** | cooked at least once, or on the wishlist |
| **new** | never cooked – score with `date_score = 5` + reward from the recipe's times and midpoint ratings; no times → **median score** |

## 5. Generate the list ✅ 🧪 ([total_score.ipynb](Testing/total_score.ipynb))
1. softmax draw of 5 from the **main** pool (no recipe together with its variant), `T` = 4, user can set 1–10
2. fewer than 5 → fill up from the **new** pool
3. swapping: in 20 % of all lists one recipe is replaced, new recipes first (never a wishlist recipe)
4. nothing left → message: browse recipes or reroll with more randomness (`T + 1`)

## 6. Website ([Server/home_find.html](../Server/home_find.html)) ✅ 🟠
- 5 proposals + buffer for dismissing; new recipes are marked **Neu**
- button **"Neue Rezepte (nie gekocht)"** → only the new pool
- filter **"Zufall (T)"** 1–10
- Server: `GET /api/propsals?user=<id>&t=<1-10>&pool=all|new`, `POST /api/propsals` with
  `meal_type, diet, include, exclude, allergies, user_id, count, t, pool`. Empty result → `message`.

## 7. Rating UI ([Server/rating.html](../Server/rating.html)) ✅ 🧪
Taste, Wdh (repeat) and effort all **0–10**, prefilled with the mean (or 5). Partial ratings are rejected
(all three ratings required, times both or none).

## 8. Cookbook PDF ([Tools/generate_cookbook_PDF.py](../Tools/generate_cookbook_PDF.py)) ✅ 🧪
Reads `Server/server_data` (same data as the website). Per recipe: times, season / type / cuisine / cooking method / spec,
ratings (mean from the history, otherwise the recipe's default rating 5, marked "Standard"), ingredient list split into
Zutaten / Grundzutaten / Gewürze with the main ingredient in **bold**. No scores that change over time.
The appendix lists only ingredients used by a recipe.

# IV. Measured Variables

Per recipe there is exactly **one** history entry. The arrays inside rotate (max. 20 values, see `RatingLogic.HISTORY_ARRAY_MAX`).

| Field | Source | Type | Meaning | Default / missing |
|---|---|---|---|---|
| `dates` | history | list ISO date | days when cooked (rated or "cooked once"), last 20 | `[]` |
| `last_date` | history | ISO date | last cooked (also via "cooked once") | missing → never cooked |
| `repeat_rating` | history | list int **0–10** | desire to repeat (5 = neutral) | `5`; dismiss / seed for uncooked recipes: `0` |
| `taste_rating` | history | list int **0–10** | taste (0 = bad, 10 = great) | `5` |
| `effort_rating` | history | list int **0–10** | effort (0 = low, **10 = high effort**) | `5` |
| `prep_minutes` / `cook_minutes` | recipe | int | times – both or none | cooked: 45 min total · never cooked: median score |
| `season` | recipe | str | season | `all` |
| `variant_of` | recipe | id / null | original recipe of a variant | `null` |
| `sweet` | recipe | bool | sweet dish | `false` |
| `veg_type` | recipe | str | vegan / vegetarian / meat | – |
| `origin` | recipe | list str | cuisine | `[]` |
| `cooking_method` | recipe | str | oven, pan, … | `null` |
| `recipe_spec` | recipe | str | soup, casserole, … | `null` |
| `main_ingredient` | recipe | `ingredient_id` / "not specific" | must be in the recipe's ingredients | `null` |
| type of meat | ingredients with `veg_type = meat` | `ingredient_id` | chicken, beef, … (`ls_meats`) | ❓ VIII.11 |
| `side_dish` | ingredient | bool | ingredient is a side (rice, noodles, …) | `false` |
| wishlist | wishlist | recipe_id, user_id | "put on next" | – |
| blacklist | blacklist | recipe_id, user_id | user doesn't like it at all | – |

# V. Database Structure

## Recipes – fields + `YamlEditor.data_problems()` ✅ 🧪

- **Season:** all, spring, summer, autumn, winter
- **Recipe type:** main dish, dessert, dip, spice mix, side dish, snack, starter
- **Recipe specs:** soup, salad, casserole, bowl, sandwich, others
  - 💡 keep it one value per recipe, so damping stays simple
- **Cooking method:** oven, pan, pot, grill, raw, steam
- **Origin:** asian, oriental, mexican, indian, italian, home-style, mediterranean, american (can have multiple)
- **Main ingredient** (if not specified): only check on creation whether the title matches the ingredients
  - can also be set to "not specific"
- **Variants:** if a recipe is saved with noodles, a variant can be the same with rice, for example.
  When creating a recipe and choosing rice as an ingredient (saved as side dish), there can be an option to automatically create variants for other choices (noodles etc.).

## Ingredients – one format for every ingredient ✅ 🧪

`ingredient_id, name, unit, veg_type, category, side_dish, lactose_free, gluten_free, shelf_life_days, kcal, protein, carbs, fat`
(order + defaults: `YamlEditor.INGREDIENT_FIELDS`; the server normalizes every save, so all forms / tools write the same format)

- **category:** `ingredient` (Zutat) · `basic` (Grundzutat: water, flour, sugar, starch, …) · `spice` (Gewürz: soy sauce, pepper, salt, …). Replaces the old `spice: true` flag.
  The cookbook PDF splits every ingredient list into Zutaten / Grundzutaten / Gewürze.
- **unit:** reference unit of the nutrition values (and default unit when adding the ingredient to a recipe). The unit in a recipe link may differ.
- **kcal, protein, carbs, fat:** per `unit` of the ingredient (g). No calculation uses them yet.
- **lactose_free / gluten_free:** `true` / `false` / `null` (= unknown, doesn't filter). Set in the ingredient forms.

## Blacklist – filter ✅ 🧪 · button / endpoint to add entries ⬜ 🟠

`server_data/blacklist.yaml`, same structure as `wishlist.yaml`: `recipe_id, user_id, date`.
Read by `propose()` (`user_blacklist`). There is no button / endpoint to add entries yet.

# VI. Old Formula (removed)

Until 2026-09-28 the app used `repeatScore` with `date_score = 10 · repeat/5 · exp(−8 · s / d_last)`.
It failed the sanity checks (cooked today → 8.0, cooked every 3 days → 10.0) and was replaced by the tanh logic.
See git history for details.

# VII. Sanity Checks → notebooks + backend test

- date_score → [Testing/date_score.ipynb](Testing/date_score.ipynb)
- reward_score → [Testing/reward_score.ipynb](Testing/reward_score.ipynb)
- damping → [Testing/damping.ipynb](Testing/damping.ipynb)
- total score, drawing, swapping, pools → [Testing/total_score.ipynb](Testing/total_score.ipynb)
- everything incl. hard filter, server, rating, PDF → [tests/test_propose_plan.py](../tests/test_propose_plan.py)

# VIII. Open Questions

1. ~~**II.1 direction of exp**~~ → replaced by tanh.
2. ~~**II.1 factor**~~ → mean/std of the gaps + rotation point + Wdh shift + correction + amplification (date_score.ipynb).
3. ~~**II.1 "without today"**~~ → without today.
4. ~~**`repeat_rating` mean or last value**~~ → mean.
5. ~~**II.2 effort**~~ → multiplicative formula, effort 0–10.
6. ~~**II.3 count rules once per candidate**~~ → merged last_supper list. Chicken hitting 3 rules (meat in last_supper, same meat, main = chicken) is intended.
7. ~~**II.3 season**~~ → bonus +3, inside the candidate loop after init.
8. ~~**III negative scores**~~ → softmax, no clamp needed.
9. ~~**II.1 factor with ≤ 1 date**~~ → ≤ 2 dates → `amp = 1`.
10. ❓ **II.3:** is the negative offset too strong? (tune in [Testing/damping.ipynb](Testing/damping.ipynb))
11. ❓ **II.3 type of meat:** app uses the ingredients with `veg_type = meat` (`recipe_features`). Keep that, or a new recipe field?
12. ~~**III wishlist damped?**~~ → wishlist 10 is damped, but `wishlist_score/5` (+2) is added undamped after damping.
13. ~~**Edge cases**~~ → decided in the "Edge Cases" table at the end of each notebook (2026-10-22).

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
- 2026-10-19 – Rearanged a lot Of Text out of ProposeLogic into Testing Nootbooks where the Explain should happen Al lot to clean yet.
- 2026-10-22 – Notebook texts rewritten, edge cases decided (user). Backend synchronised with the notebooks: date_score (rotation point from history, Wdh shift + correction with the recipe's own mean, amplification, new-user guards), reward (effort 0–10, midpoint defaults, `max(0, time)`), damping (same meat −3, meats counted per meal, main_ingredient attributes from `ingredients.yaml`, error if not in the recipe). New: pool of never cooked recipes (median score without times, fills short lists, swaps, website button "Neue Rezepte"), `T` = 4 adjustable 1–10, wishlist overrides `remove`, empty-result message + reroll. Effort UI + data 0–10, partial ratings rejected. Cookbook PDF shows ratings + reward. This doc reduced to the overview. Backend test 94/94, every notebook checks `notebook == backend`, new `test_with_data.ipynb`.
