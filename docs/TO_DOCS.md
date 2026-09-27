What's still open

The server doesn't use propose() yet. /api/propsals still runs filter_recipes + weighted_shuffle. I checked through Flask's test client (no running server needed) that it behaves as before.
On your real data propose() returns an empty list. Recipe 52 has prep_minutes: 60, and the same-day filter removes anything at ≥ 60. Should it be > 60?
Damping doesn't work on real data yet. The recipes still lack origin, cooking_method, recipe_spec and main_ingredient, so those rules don't fire.
Meat type: the code uses the ingredients with veg_type = meat as the meat types. This is open question 11; it's the only place you'd need to change if you decide otherwise.
The allergy filter isn't built. lactose_free and gluten_free aren't in the data yet.
Nothing is committed.