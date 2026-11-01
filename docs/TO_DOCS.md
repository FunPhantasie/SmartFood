What's still open (2026-11-01)

Logic, server and UI are complete: proposals (GET + POST /api/proposals), several main ingredients, meat types
(fish counts as a meat type), blacklist (button on cards + recipe page), allergy filter on the home page.
Test: python tests/test_propose_plan.py -> 127/127 (also checks the real server_data, so it keeps working when recipes are added).
All notebooks in docs/Testing run (notebook == backend).

Next: try the whole flow in the browser and use the app normally (cook, rate, dismiss).

Data:
1. Recipes without main_ingredient or origin are allowed. 59 recipes have no side_dish - check over time which really have none.
2. gluten_free / lactose_free are filled for all ingredients. Product-dependent ones (broths, Brühwürfel, Reiswein, Miso,
   Worcestersauce, Streuwürze, Toastbrot, Burgerbrötchen) are set to "contains" - correct them in the form if your product is free.
   Ripened cheeses (incl. Feta) count as lactose free.
3. Meat types: mixed minced meat (Hackfleisch gemischt) is set to beef - tick pork in those recipes if wanted.
4. History has only 1 entry - date_score / reward only become meaningful after cooking + rating for a while.

Open questions (docs/ProposeLogic.md VIII): #10 negative offset - watch it in real use.
