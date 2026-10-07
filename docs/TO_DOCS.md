What's still open (2026-10-07)

The propose logic is done and connected: GET + POST /api/propsals run ProposeLogic.propose(). Test: python tests/test_propose_plan.py -> 63/63 (also checks the real server_data, so it keeps working when recipes are added).

Data / UI, not logic:
1. Recipe fields origin, cooking_method, recipe_spec, main_ingredient exist (creation page). Only Pekingsuppe is filled in.
2. Ingredient fields lactose_free / gluten_free exist (creation + ingredients page), all 22 still "unknown" (null). The home page doesn't send "allergies" yet (POST field exists).
3. Blacklist: server_data/blacklist.yaml is read, but there is no button / endpoint to add entries.
4. Only 1 recipe in server_data/recipes.yaml; data/recipes_generated.yaml has 322 not imported.
5. RatingLogic.recipe_scores / weighted_shuffle are no longer used by the server.

Open questions (docs/ProposeLogic.md VIII): #2 factor speed, #10 negative offset, #11 meat type (veg_type = meat ingredients).
