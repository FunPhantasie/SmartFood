#!/usr/bin/env python3
"""
ingredients_tool.py — Add or edit ingredients in YAML storage.
Usage examples:

# Add new ingredient
python ingredients_tool.py --ingredients ingredients.yaml add \
  --name "Flour" --veg-type vegetarian --shelf-life-days 180 \
  --side-dish false --cost-eur 1.2 --stock-amount 1000 --unit g

# Edit an ingredient by id
python ingredients_tool.py --ingredients ingredients.yaml edit \
  --id 1 --cost-eur 1.35 --stock-amount 850

# List ingredients (optional helper)
python ingredients_tool.py --ingredients ingredients.yaml list
"""
import argparse, sys, yaml

VALID_VEG = {"meat","vegan","vegetarian"}

def load_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {"ingredients":[]}

def save_yaml(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def next_ing_id(doc):
    arr = doc.get("ingredients", [])
    max_id = 0
    for r in arr:
        rid = int(r.get("ingredient_id", 0) or 0)
        if rid > max_id: max_id = rid
    return max_id + 1

def parse_bool(s: str) -> bool:
    s = s.strip().lower()
    if s in ("1","true","yes","y","on"):
        return True
    if s in ("0","false","no","n","off"):
        return False
    raise argparse.ArgumentTypeError("Expected boolean (true/false)")

def add_cmd(args):
    doc = load_yaml(args.ingredients) or {"ingredients":[]}
    new_id = next_ing_id(doc)
    if args.veg_type and args.veg_type not in VALID_VEG:
        raise SystemExit(f"veg_type must be one of {sorted(VALID_VEG)}")

    rec = {
        "ingredient_id": new_id,
        "name": args.name,
        "shelf_life_days": args.shelf_life_days,
        "veg_type": args.veg_type,
        "side_dish": args.side_dish,
        "cost_eur": args.cost_eur,
        "stock_amount": args.stock_amount,
        "unit": args.unit,
    }
    doc.setdefault("ingredients", []).append(rec)
    save_yaml(args.ingredients, doc)
    print(f"OK: added ingredient_id={new_id} ({args.name})")

def edit_cmd(args):
    doc = load_yaml(args.ingredients) or {"ingredients":[]}
    arr = doc.get("ingredients", [])
    target = None
    for r in arr:
        if int(r.get("ingredient_id", -1)) == int(args.id):
            target = r; break
    if not target:
        raise SystemExit(f"ingredient_id={args.id} not found")

    # Apply updates if provided
    if args.name is not None: target["name"] = args.name
    if args.shelf_life_days is not None: target["shelf_life_days"] = args.shelf_life_days
    if args.veg_type is not None:
        if args.veg_type not in VALID_VEG:
            raise SystemExit(f"veg_type must be one of {sorted(VALID_VEG)}")
        target["veg_type"] = args.veg_type
    if args.side_dish is not None: target["side_dish"] = args.side_dish
    if args.cost_eur is not None: target["cost_eur"] = args.cost_eur
    if args.stock_amount is not None: target["stock_amount"] = args.stock_amount
    if args.unit is not None: target["unit"] = args.unit

    save_yaml(args.ingredients, doc)
    print(f"OK: updated ingredient_id={args.id}")

def list_cmd(args):
    doc = load_yaml(args.ingredients) or {"ingredients":[]}
    for r in doc.get("ingredients", []):
        print(f"{r.get('ingredient_id'):>4}  {r.get('name','(no name)')}  "
              f"{r.get('veg_type','-')}  {r.get('stock_amount','-')}{r.get('unit','')}  "
              f"€{r.get('cost_eur','-')}")

def main(argv=None):
    p = argparse.ArgumentParser(description="Add or edit ingredients.")
    p.add_argument("--ingredients", required=True, help="ingredients.yaml path")

    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="Add a new ingredient")
    pa.add_argument("--name", required=True)
    pa.add_argument("--veg-type", required=True)
    pa.add_argument("--shelf-life-days", type=int, default=None)
    pa.add_argument("--side-dish", type=parse_bool, required=True)
    pa.add_argument("--cost-eur", type=float, default=None)
    pa.add_argument("--stock-amount", type=float, default=None)
    pa.add_argument("--unit", default=None)
    pa.set_defaults(func=add_cmd)

    pe = sub.add_parser("edit", help="Edit an existing ingredient by id")
    pe.add_argument("--id", type=int, required=True)
    pe.add_argument("--name")
    pe.add_argument("--veg-type")
    pe.add_argument("--shelf-life-days", type=int)
    pe.add_argument("--side-dish", type=parse_bool)
    pe.add_argument("--cost-eur", type=float)
    pe.add_argument("--stock-amount", type=float)
    pe.add_argument("--unit")
    pe.set_defaults(func=edit_cmd)

    pl = sub.add_parser("list", help="List ingredients")
    pl.set_defaults(func=list_cmd)

    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    import sys
    sys.exit(main())
