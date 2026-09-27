# Propose Logic – Formulas & Sanity Checks


Every formula is written down here as planned or as implemented, so code and idea can be checked against each other later.

> Status: **work in progress**
> - ✅ date_score (old formula in code, see VI – new formula in II.1 not implemented yet)
> - 🚧 reward_score
> - ⬜ damp_score, filter, generation list
>
> 💡 = suggestion, not decided yet

---

# I. Overview

1. Load all data (could be inefficient)
   1. Recipes
   2. History
   3. Recipe ingredients
   4. BlackListed Recipe (User Doesnt Like at all)
2. From history calculate **date_score**
   - Distances in `dates` (array[date])
   - Distance last cooked ↔ today: `last_date` (date)
   - Repeat score: `repeat_rating` (int)
3. From history estimate effort vs. result (**reward_score**)
   - `taste_rating`, `effort_rating`, `prep_minutes` + `cook_minutes`
4. Damp recently cooked meals (**damp_score**)
5. Filter out variants of recently cooked meals
6. Generate list (top 5 + swapping)

# II. Methods

## 1. `repeatScore()` → date_score

```
take dates
if len(dates) <= 1: factor = 1                (without today)
avg_dist  = mean distance between dates, floored to days
dist_last = distance last_date ↔ today, floored to days

factor = max(1, 4 - avg_dist/14)              # repeating every 14 days results in a good score
         TODO later: calibrate with number of recipes

factor → g(factor) ∈ (0, 1)
  choose between 1 - exp(-x) and exp(-1/x)
  → take 1 - exp(-x) (easier to tune / predict)

date_score = 10/5 · repeat_rating · exp(-factor · dist_last / 8)
Result: date_score ∈ [0, 10]
```

## 2. `dopaminscore()` → reward_score

```
Filter Same Day Cooking If either cook_minutes | prep_minutes >= 1h Out
time      = cook_minutes + prep_minutes
cookscore = 1/(1+exp((-50+time) / 7.5))               # 7.5 min as unit – 
Were bei 50min = 0.5 40min= 0.8

reward    = cookscore*(taste_rating+1.5*effort_rating)*0,4 ∈ (0, 5]
```



## 3. `damping_score()` → damp_score, last_supper

```
load the last 3 cooked meals → last_supper (array[ids])
ignore if longer than 4 days ago
load ingredients from recipe_ingredients for last_supper
init damp_score_mult= 1
damp_score_offset=0
create filter list:
  - side_dish
  - meat
  - main ingredient
  - recipe specs soup soup
  - sweet
If Season Overlap(All also)  offset  +3
If Origin double offset  -1
If Cooking method double Nothing
If sweet, soup ,Casserole again damp_score_mult* (1-80%) 
If side_dish double offset  -3
If meal_type=meat==True    damp_score_mult *(1-10% * number)
mit (1-x)**n >= 1-nx | (1-xn)**n >= 1-n**2x
If meat double offset -5
If main Ingredient (exists) and double  
    If Main Incredient ==sidedish damp_score_mult *(1-10%)
    If Main Incredient ==meat  damp_score_mult *(1-10%)
    If Above Both False: offset  -3
```

💡

## 4. `filter_score()` → final list

```
load all variants of last_supper (recipe field variant_of)
filter out all repeats of variants and original (last_supper)
```

# III. Generation List

> Uses: date_score | reward_score | never_cooked | wishlist | blacklist
If wishlist Wishlistscore = 6
score= (date_score+reward_score+Wishlistscore)*damp_score_mult+damp_score_offset

> Calculate score And Randmomize Draw mit Rausnehmen with Score Choose 5.
> For Drawing 1 Already Remove than the Variants out of Drawing Cointainer

**Swapping out recipes**

- X: meal is proposed ("proposed")
- ¬X: meal is never cooked ("never cooked")
- Y = number of X with n = 5 tries, Y ~ Bin(5, p)
- **Given:** P(Y = 5) = p⁵ = 0.8 → p ≈ 0.956
- P(¬X) = 1 − p ≈ 0.044 = w

For each proposal: swap with probability 1 − p.
Skip if on wishlist.

💡 Swap candidates: never cooked recipes first, then random from the rest (excluding last_supper and its variants).

# IV. Measured Variables

Per recipe there is exactly **one** history entry. The arrays inside rotate (max. 20 values, see `RatingLogic.HISTORY_ARRAY_MAX`).

| Field | Source | Type | Meaning | Default / missing |
|---|---|---|---|---|
| `dates` | history | list ISO date | days when rated (cooked) | `[]` |
| `last_date` | history | ISO date | last cooked (also via "cooked once") | missing → never cooked |
| `repeat_rating` | history | list int 1–5 | desire to repeat | `3`; seed for uncooked recipes: `[1]` |
| `taste_rating` | history | list int 1–5 | taste | – |
| `effort_rating` | history | list int 1–5 | effort | – |
| `prep_minutes` / `cook_minutes` | recipe | int | times | – |
| `season` | recipe | str | season | `always` |

# V. Database Structure

## Recipes

- **Season:** all, spring, summer, autumn, winter
- **Recipe type:** main dish, dessert, dip, spice mix, side dish, snack, starter
- **Recipe specs:** soup, salad, casserole, bowl, sandwich, others
  - 💡 keep it one value per recipe, so damping (II.3) stays simple
- **Cooking method:** oven, pan, grill, raw,steam
  
- **Origin:** asian, oriental, mexican,indian, italian, home-style, mediterranean (can have multiple)
  
- **Main ingredient** (if not specified): only check on creation whether the title matches the ingredients
  - can also be set to "not specific"

- **Varaints**  If an Recipe is Saved with Noodles a Variant can be just with Rice for Example 
When Creating a Recipe and Choosing Rice and incredient (Its saved as Sidedish) there can be an option to create Automatically Varaints for different Choices Noodles etc.

## Ingredients

`ingredient_id, name, unit, veg_type, lactose_free, gluten_free, specs_ingredient`

- **specs_ingredient:** side_dish, spice, basics (e.g. water, flour,butter,oil, …)
 

# VI. Current Code: `date_score` (old formula)

Code: `repeatScore(entry, today)` and `calcAvgDistanceScore(avg_dist)` – to be replaced by II.1.

```
avg_dist    = mean day distance between consecutive (dates + today)
s(avg_dist) = max(0, 3 − 10 / avg_dist)          (0 if avg_dist = 0)
repeat      = mean repeat_rating
d_last      = days since last_date

date_score  = 10 · repeat/5 · exp(−8 · s / d_last)
```

**Edge cases**

| Case | Handling |
|---|---|
| no `dates` | `avg_dist = 1` → `s = 0` → no penalty |
| no `last_date` (never cooked) | `d_last = ∞` → factor 1 → `date_score = 2 · repeat` |
| `d_last = 0` (cooked today) | set to 1 day (no division by 0) |
| empty `repeat_rating` | `repeat = 3` |

**Examples** (today = 2026-09-23, calculated with the real code)

| # | Situation | avg_dist | s | d_last | repeat | date_score |
|---|---|---|---|---|---|---|
| A | never cooked (seed) | – | 0 | ∞ | 1 | **2.00** |
| B | cooked once, today | 0 | 0 | 1 | 4 | **8.00** ⚠️ |
| C | recipe 52: once, 7 days ago | 7 | 1.57 | 7 | 3 | **1.00** |
| D | every 20 days, last 13 days ago | 17.7 | 2.43 | 13 | 4 | **1.79** |
| E | every ~90 days, last 90 days ago | 90 | 2.89 | 90 | 5 | **7.74** |
| F | every 3 days, last 3 days ago | 3 | 0 | 3 | 5 | **10.00** ⚠️ |

# VII. Sanity Checks

Expected behavior. Every row should match an example above (or a test).

| Situation | Expected | Current (date_score, old) | OK? |
|---|---|---|---|
| just cooked | very low (~0) | B: 8.00 | ❌ |
| cooked very often, recently | low | F: 10.00 | ❌ |
| cooked rarely, long ago | high (~2·repeat) | E: 7.74 of max. 10 | ✅ |
| normal rhythm, in between | medium | D: 1.79 | ❓ |
| never cooked | neutral-low (seed repeat 1) | A: 2.00 | ✅ |
| higher repeat ⇒ higher score (rest equal) | monotonically increasing | linear in repeat | ✅ |
| longer ago ⇒ higher score (rest equal) | monotonically increasing | yes, as long as s > 0 | ✅ |

# VIII. Open Questions

1. **II.1 direction of exp:** `1 − exp(−x)` is chosen, but the formula says `exp(−factor · dist_last / 8)`. That makes the score *smaller* the longer ago `last_date` is (cooked today → maximum). Probably meant: `date_score = 2 · repeat_rating · (1 − exp(−dist_last / (8 · factor)))`?
2. **II.1 factor:** only bounded by `max(1, …)` → factor ∈ [1, 4]. Should `g(factor)` be applied separately afterwards, or is it already part of the exp formula?
3. **II.1 "without today":** should `today` count for `avg_dist` (old code: yes)?
4. `repeat_rating` is an array → mean or last value?
5. Normalize `date_score` to 0–1 so it can be combined with reward_score?

## Changelog

- 2026-09-23 – Draft created, `date_score` (old formula) implemented and documented.
- 2026-09-27 – New plan (II–V) added, cleaned up; old formula moved to VI.
- 2026-09-27 – Translated to English, suggestions (💡) added for filter list, recipe specs and more.
