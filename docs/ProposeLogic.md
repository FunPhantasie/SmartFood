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
| **main** | cooked at least once, rated ahead (developer page `/dev`), or on the wishlist – all per user |
| **new** | never cooked and not rated ahead – score with `date_score = 5` + reward from the recipe's times and midpoint ratings; no times → **median score** |

## 5. Generate the list ✅ 🧪 ([total_score.ipynb](Testing/total_score.ipynb))
1. softmax draw of 5 from the **main** pool (no recipe together with its variant), `T` = 4, user can set 1–10
2. fewer than 5 → fill up from the **new** pool
3. swapping: in 20 % of all lists one recipe is replaced, new recipes first (never a wishlist recipe)
4. nothing left → message: browse recipes or reroll with more randomness (`T + 1`)
5. every proposal remembers where it came from (`propose_detailed`, `SOURCE_*`): `cycle` (main pool), `fill`
   (filled up from the new pool), `swap_new` / `swap_main` (swapped in, with the replaced recipe), `new_pool` (button)

## 6. Website ([Server/home_find.html](../Server/home_find.html)) ✅ 🟠
- 5 proposals + buffer for dismissing; new recipes are marked **Neu**
- badge with the source: **Zyklus** / **Aufgefüllt** / **Getauscht** (+ "getauscht statt …") / **Neue Rezepte**,
  plus **Wunschliste** and the total score (tooltip explains it)
- button **"Neue Rezepte (nie gekocht)"** → only the new pool
- filter **"Zufall (T)"** 1–10
- filter **"Unverträglichkeiten"** (Laktosefrei / Glutenfrei) – remembered in the browser, sent with every request
- include / exclude suggest the real ingredient names; meal types = the `recipe_type` values of the data
- panel **"Rezept suchen"**: every word must be in the recipe name or one of its ingredients (umlauts ignored),
  name hits first, max. 30 – click → recipe page. Reads `/api/all`, no extra endpoint
- card buttons: **×** = not now (`repeat_rating` 0), **🚫** = never propose again (blacklist, needs a user)
- Server: `GET /api/proposals?user=<id>&t=<1-10>&pool=all|new&allergies=lactose,gluten`, `POST /api/proposals` with
  `meal_type, diet, include, exclude, allergies, user_id, count, t, pool`. Empty result → `message`.

## 7. Rating UI ([Server/rating.html](../Server/rating.html)) ✅ 🧪
Taste, Wdh (repeat) and effort all **0–10**, prefilled with the mean (otherwise the rating ahead, otherwise 5).
Rating sets **today** as cooking date – for dishes you know but didn't cook today, use the developer page `/dev` below. Partial ratings are rejected
(all three ratings required, times both or none).

## 8. Cookbook PDF ([Tools/generate_cookbook_PDF.py](../Tools/generate_cookbook_PDF.py)) ✅ 🧪
Reads `Server/server_data` (same data as the website). Per recipe: times, season / type / cuisine / cooking method / spec,
ratings (mean from the history, otherwise the recipe's default rating 5, marked "N.R."), ingredient list split into
Zutaten / Grundzutaten / Gewürze with the main ingredient in **bold**. No scores that change over time.
The appendix lists only ingredients used by a recipe.

# IV. Measured Variables

Per recipe there is exactly **one** history entry. The arrays inside rotate (max. 20 values, see `RatingLogic.HISTORY_ARRAY_MAX`).

| Field | Source | Type | Meaning | Default / missing |
|---|---|---|---|---|
| `dates` | history | list ISO date | days when cooked (rated or "cooked once"), last 20 | `[]` |
| `last_date` | history | ISO date | last cooked (also via "cooked once") | missing → never cooked |
| `repeat_rating` | history | list int **0–10** | desire to repeat (5 = neutral) | rating ahead, else `5`; dismiss: `0` |
| `taste_rating` | history | list int **0–10** | taste (0 = bad, 10 = great) | rating ahead, else `5` |
| `effort_rating` | history | list int **0–10** | effort (0 = low, **10 = high effort**) | rating ahead, else `5` |
| `prep_minutes` / `cook_minutes` | recipe | int | times – both or none | cooked: 45 min total · never cooked: median score |
| `season` | recipe | str | season | `all` |
| `variant_of` | recipe | id / null | original recipe of a variant | `null` |
| `sweet` | recipe | bool | sweet dish | `false` |
| `veg_type` | recipe | str | vegan / vegetarian / fish / meat (from the ingredients) | – |
| `origin` | recipe | list str | cuisine | `[]` |
| `cooking_method` | recipe | str | oven, pan, … | `null` |
| `recipe_spec` | recipe | str | soup, casserole, … | `null` |
| `main_ingredient` | recipe | list of `ingredient_id` / `null` | main ingredient(s), each must be in the recipe's ingredients – damping (`ls_mains`). A single id is still read | `null` = none → not damped |
| `side_dish` | recipe | `ingredient_id` / `null` | side dish (rice, noodles, …), must be in the recipe's ingredients – damping (`ls_sides`), variants | `null` = none → not damped |
| `meat_types` | recipe | list str | meat types of the dish (`ls_meats`): set from the ingredients' `meat_type` whenever the ingredient list is edited, adjustable | missing → from the ingredients |
| `meat_type` | ingredient | str / null | beef, pork, poultry, lamb, game, fish, other – only for `veg_type = meat / fish` | `null` = no meat type (broth, instant ramen, oyster / worcester sauce) |
| `side_dish` | ingredient | bool | ingredient is a side (rice, noodles, …) | `false` |
| wishlist | wishlist | recipe_id, user_id | "put on next" | – |
| blacklist | blacklist | recipe_id, user_id | user doesn't like it at all | – |

# V. Database Structure

## Recipes – fields + `YamlEditor.data_problems()` ✅ 🧪

- **Season:** all, spring, summer, autumn, winter
- **Recipe type:** main dish, dessert, dip, spice mix, side dish, snack, starter
- **Recipe specs:** soup, stew, salad, pasta, pan_dish, casserole, bowl, sandwich, baked, sauce, others (same as the cookbook PDF)
  - one value per recipe, so damping stays simple; only soup / casserole (+ `sweet`) are damped
- **Cooking method:** oven, pan, pot, grill, raw, steam, microwave
- **Origin:** asian, oriental, mexican, indian, italian, home-style, mediterranean, american (can have multiple)
- **Main ingredient + side dish** ✅ 🧪 (`creation.html`, `YamlEditor.suggest_main_and_side`, `POST /api/recipe/suggest`):
  - the app **suggests** both – main: a normal ingredient whose name is in the recipe name, otherwise the one with the largest weight share; side: an ingredient with `side_dish: true`
  - **several main ingredients** possible (checkboxes); damping: the main rule fires once, `×0.9` if one of the shared mains is meat / a side, otherwise `−3`
  - only a suggestion: saving is blocked until both are confirmed ("Übernehmen", own choice or "keine")
  - "keine" → `null` (e.g. Pekingsuppe); such a recipe is not damped via main / side
- **Variants** ✅ 🧪 (`variant_of` = main recipe of the family):
  - button "Variante mit anderer Beilage": copies the saved recipe, swaps the side dish, saves the copy as variant
  - saving a recipe with the same ingredients as an existing one but another side dish asks "als Variante speichern?" (`YamlEditor.side_dish_variant_of`)
  - the cookbook PDF links all variants of a family after the instructions (name, side dish, page)
- **Meat types** ✅ 🧪 (`meat_types`, `YamlEditor.meat_types_of`): checkboxes in `creation.html`, set from the ingredients'
  `meat_type` on every change of the ingredient list, can be adjusted before saving. Damping reads the recipe field.

## Ingredients – one format for every ingredient ✅ 🧪

`ingredient_id, name, unit, veg_type, meat_type, category, side_dish, lactose_free, gluten_free, shelf_life_days, kcal, protein, carbs, fat`
(order + defaults: `YamlEditor.INGREDIENT_FIELDS`; the server normalizes every save, so all forms / tools write the same format)

- **category:** `ingredient` (Zutat) · `basic` (Grundzutat: water, flour, sugar, starch, …) · `spice` (Gewürz: soy sauce, pepper, salt, …). Replaces the old `spice: true` flag.
  The cookbook PDF splits every ingredient list into Zutaten / Grundzutaten / Gewürze.
- **unit:** reference unit of the nutrition values (and default unit when adding the ingredient to a recipe). The unit in a recipe link may differ.
- **kcal, protein, carbs, fat:** per `unit` of the ingredient (g). No calculation uses them yet.
- **veg_type:** vegan · vegetarian · fish · meat
- **meat_type:** only for meat / fish: beef · pork · poultry · lamb · game · fish · other, `null` = doesn't count as a meat type (broth, fish sauces).
  Fish is handled exactly like meat (meat type `fish`; a fish main ingredient counts as meat for the main rule) – no extra logic.
  Mixed minced meat is `beef` – tick pork in the recipe if needed.
- **lactose_free / gluten_free:** `true` / `false` / `null` (= unknown, doesn't filter). Set in the ingredient forms.

## Blacklist ✅ 🧪

`server_data/blacklist.yaml`, same structure as `wishlist.yaml`: `recipe_id, user_id, date`.
Read by `propose()` (`user_blacklist`). Added / removed with `POST /api/blacklist/toggle {recipe_id, user_id}`
(user required): button **🚫** on the proposal cards and **"Nicht mehr vorschlagen"** on the recipe page (also undo).
A recipe is on at most one of wishlist / blacklist per user – adding it to one removes it from the other.

## Per-user data – `server_data/user_data/user_<id>.yaml` ✅ 🧪

One file per user (`user_id` from `users.yaml`) with two lists:
- `history` – per recipe one entry: dates, ratings, times (structure see IV)
- `default_ratings` – ratings ahead: `recipe_id, name, taste_rating, effort_rating, repeat_rating` (0–10 / `null`)

The server loads the selected user's file into `data["history"]` / `data["default_ratings"]` (`load_all(user)`), so the
logic itself is unchanged. No (known) user → both empty: proposals still work (everything new), but rating,
"cooked once", dismiss and `/dev` answer **400**. Only ids from `users.yaml` are accepted (the id is in the file name).
Changing the user in the nav reloads the page. The cookbook PDF averages over all users (`RatingLogic.merge_histories`).

**Ratings ahead** – developer page **`/dev`** ([Server/dev.html](../Server/dev.html)): recipes the user hasn't rated yet
(no rating ahead, no taste rating in the history) in random order; 0–10 buttons for taste / effort / repeat (repeat
starts at 5), save, skip, reshuffle, filter by type, optionally show the rated ones to change / delete them.
`GET /api/dev/ratings?user=`, `POST /api/dev/rating {user_id, recipe_id, taste_rating, effort_rating, repeat_rating}`
(all `null` = remove). A value is used only while the history has no rating for it (`ProposeLogic.rating`: history mean →
rating ahead → 5); **no cooking date** is set, so `date_score` stays 5. A recipe with any value counts as known: main pool,
no **Neu** badge (`RatingLogic.is_new`).

## Who owns which data
- **per user:** `user_data/user_<id>.yaml` (history + ratings ahead), entries in `wishlist.yaml` / `blacklist.yaml` (`user_id`)
- **shared:** recipes, recipe_ingredients, ingredients, users

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
11. ~~**II.3 type of meat**~~ → recipe field `meat_types`, filled from the ingredients' `meat_type` when the recipe is edited (user, 2026-11-01).
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
- 2026-11-01 – `main_ingredient` may be a list (several main ingredients: logic, `data_problems`, creation page checkboxes).
  Meat types (VIII.11): ingredient field `meat_type` + recipe field `meat_types` (broth / instant ramen no longer count as meat).
  Blacklist button + `POST /api/blacklist/toggle`, allergy filter on the home page (also GET `?allergies=`), `veg_type` fish in
  the forms, recipe specs / cooking methods aligned with the cookbook PDF. Endpoint renamed `/api/propsals` → `/api/proposals`.
  Removed unused `RatingLogic.recipe_scores` / `weighted_shuffle` / `ensure_uncooked_seed` and `/api/create/<id>`. Backend test 126/126.
- 2026-11-01 – fish handled like meat: meat type `fish` (salmon, tuna, redfish; fish sauces `null`), main rule treats a fish main as meat.
  All unknown `gluten_free` / `lactose_free` filled (product-dependent → "contains", so the filter rather excludes too much). Backend test 127/127.
- 2026-11-01 – Recipe search on the home page (name + ingredients). Admin file `default_ratings.yaml`: ratings ahead per recipe (fallback before 5, rated ahead = known / main pool), synced by the server. creation.html / ingredients.html no longer send `history` / `users` when saving (an old copy overwrote newer ratings). Backend test 132/132.
- 2026-11-01 – History per user: `server_data/user_data/user_<id>.yaml` (history + ratings ahead), the old `history.yaml` moved to user 1 (Tim), the admin file `default_ratings.yaml` replaced by the developer page `/dev`. Rating / cooked / dismiss need a user. Cookbook averages over all users. Backend test 137/137.
- 2026-11-01 – Proposal source shown on the cards (`ProposeLogic.propose_detailed`: cycle / fill / swap / new pool + score). Backend test 143/143.
