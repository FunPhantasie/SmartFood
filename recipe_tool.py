#!/usr/bin/env python3
"""
recipe_tool.py — Add new recipes (and link ingredients)
Usage examples:

# Minimal recipe (no ingredients yet)
python recipe_tool.py \
  --recipes recipes.yaml \
  --recipe-ingredients recipe_ingredients.yaml \
  --name "Chili sin Carne" \
  --veg-type vegan \
  --duration 45 \
  --sweet false \
  --instructions "Sauté onions; add beans, tomatoes, spices; simmer 30 min."

# Recipe with ingredients (ingredient_id:quantity:unit)
python recipe_tool.py \
  --recipes recipes.yaml \
  --recipe-ingredients recipe_ingredients.yaml \
  --ingredients-file ingredients.yaml \
  --name "Pancakes" \
  --veg-type vegetarian \
  --duration 20 \
  --sweet true \
  --instructions "Mix; rest 5 min; fry in pan." \
  --ingredient 1:250:g \
  --ingredient 2:2:pcs \
  --ingredient 3:300:ml

Notes
-----
- veg_type must be one of: meat, vegan, vegetarian
- sweet: true/false
- If --ingredients-file is provided, ingredient IDs will be validated.
"""
import argparse, sys, yaml, os
from typing import List, Tuple

VALID_VEG = {"meat","vegan","vegetarian"}

def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def next_recipe_id(recipes_doc):
    arr = recipes_doc.get("recipes", [])
    max_id = 0
    for r in arr:
        rid = int(r.get("recipe_id", 0) or 0)
        if rid > max_id:
            max_id = rid
    return max_id + 1

def parse_bool(s: str) -> bool:
    s = s.strip().lower()
    if s in ("1","true","yes","y","on"):
        return True
    if s in ("0","false","no","n","off"):
        return False
    raise argparse.ArgumentTypeError("Expected boolean for --sweet (true/false)")

def parse_ingredient_arg(s: str) -> Tuple[int, float, str]:
    # format: id:quantity:unit
    parts = s.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Ingredient format must be id:quantity:unit")
    try:
        iid = int(parts[0])
        qty = float(parts[1])
        unit = parts[2]
    except Exception:
        raise argparse.ArgumentTypeError("Invalid ingredient triplet")
    return (iid, qty, unit)

def validate_ingredient_ids(ids: List[int], ingredients_file: str):
    if not ingredients_file:
        return
    data = load_yaml(ingredients_file) or {}
    have = {int(x.get("ingredient_id")) for x in data.get("ingredients", []) if x.get("ingredient_id") is not None}
    missing = [i for i in ids if i not in have]
    if missing:
        raise SystemExit(f"Ingredient IDs not found in {ingredients_file}: {missing}")

def main(argv=None):
    p = argparse.ArgumentParser(description="Add a new recipe to YAML storage.")
    p.add_argument("--recipes", required=True, help="recipes.yaml path")
    p.add_argument("--recipe-ingredients", required=True, help="recipe_ingredients.yaml path")
    p.add_argument("--ingredients-file", default=None, help="ingredients.yaml (optional for ID validation)")
    p.add_argument("--name", required=True)
    p.add_argument("--veg-type", required=True, choices=sorted(VALID_VEG))
    p.add_argument("--duration", type=int, required=True, help="minutes")
    p.add_argument("--sweet", type=parse_bool, required=True)
    p.add_argument("--instructions", required=True)
    p.add_argument("--variant-of", type=int, default=None, help="recipe_id of base recipe; omit if none")
    p.add_argument("--ingredient", action="append", default=[], help="ingredient_id:quantity:unit (repeatable)")

    args = p.parse_args(argv)

    # Load docs
    recipes_doc = load_yaml(args.recipes) or {"recipes":[]}
    links_doc = load_yaml(args.recipe_ingredients) or {"recipe_ingredients":[]}

    new_id = next_recipe_id(recipes_doc)

    # Validate ingredients if requested
    ing_triplets = [parse_ingredient_arg(s) for s in args.ingredient]
    validate_ingredient_ids([i for (i,_,_) in ing_triplets], args.ingredients_file)

    # Create recipe
    rec = {
        "recipe_id": new_id,
        "veg_type": args.veg_type,
        "duration_minutes": args.duration,
        "name": args.name,
        "sweet": bool(args.sweet),
        "instructions": args.instructions,
        "variant_of": args.variant_of if args.variant_of is not None else None,
    }
    recipes_doc.setdefault("recipes", []).append(rec)

    # Add links
    for iid, qty, unit in ing_triplets:
        links_doc.setdefault("recipe_ingredients", []).append({
            "ingredient_id": int(iid),
            "recipe_id": int(new_id),
            "quantity": float(qty),
            "unit": unit,
        })

    save_yaml(args.recipes, recipes_doc)
    save_yaml(args.recipe_ingredients, links_doc)

    print(f"OK: added recipe_id={new_id} with {len(ing_triplets)} ingredient link(s).")

if __name__ == "__main__":
    sys.exit(main())
