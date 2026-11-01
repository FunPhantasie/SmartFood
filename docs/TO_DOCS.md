What's still open (2026-11-01)

Logic, server and UI are complete: proposals (GET + POST /api/proposals), several main ingredients, meat types
(fish counts as a meat type), blacklist (button on cards + recipe page), allergy filter + recipe search on the home page,
history + ratings ahead per user (Server/server_data/user_data/user_<id>.yaml), developer page /dev for ratings ahead.
Test: python tests/test_propose_plan.py -> 143/143 (also checks the real server_data, so it keeps working when recipes are added).
All notebooks in docs/Testing run (notebook == backend).

Next: rate the dishes you know on /dev (per user), try the whole flow in the browser and use the app normally
(cook, rate, dismiss). Rate on the rating page only what you really cooked that day - it sets today as cooking date.

Data:
1. Recipes without main_ingredient or origin are allowed. 59 recipes have no side_dish - check over time which really have none.
2. gluten_free / lactose_free are filled for all ingredients. Product-dependent ones (broths, Brühwürfel, Reiswein, Miso,
   Worcestersauce, Streuwürze, Toastbrot, Burgerbrötchen) are set to "contains" - correct them in the form if your product is free.
   Ripened cheeses (incl. Feta) count as lactose free.
3. Meat types: mixed minced meat (Hackfleisch gemischt) is set to beef - tick pork in those recipes if wanted.
4. History: user 1 (Tim) has 1 entry (moved from the old history.yaml), user 2 none - date_score / reward only become meaningful after cooking + rating for a while.

Open questions (docs/ProposeLogic.md VIII): #10 negative offset - watch it in real use.
