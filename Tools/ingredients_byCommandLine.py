#!/usr/bin/env python3
"""
ingredients_byCommandLine.py — Add or edit ingredients in YAML storage.
Usage examples:

Works on Server/server_data/ingredients.yaml (same data + format as the website).

# Add new ingredient (nutrition values per --unit)
python ingredients_byCommandLine.py add --name "Mehl" --veg-type vegan --side-dish false \
  --category basic --unit EL --kcal 35 --protein 1.0 --carbs 7.2 --fat 0.1

# Edit an ingredient by id (only the given fields change)
python ingredients_byCommandLine.py edit --id 1 --category spice

# List ingredients
python ingredients_byCommandLine.py list
"""
import argparse, sys, yaml
import YamlEditor as yr
import sys
from pathlib import Path

VALID_VEG = {"meat","vegan","vegetarian"}

# ------------------------------------------------------------
# Pfade (wie von dir gewünscht)
# ------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = APP_DIR / "Server" / "server_data"   # gleiche Daten wie die Website

RECIPES_YAML = DATA_DIR / "recipes.yaml"
RECIPE_INGREDIENTS_YAML = DATA_DIR / "recipe_ingredients.yaml"
INGREDIENTS_YAML = DATA_DIR / "ingredients.yaml"



def _validate_veg_type(veg_type: str | None) -> None:
    if veg_type is not None and veg_type not in VALID_VEG:
        raise SystemExit(f"veg_type must be one of {sorted(VALID_VEG)}")



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

EDITABLE = ("name", "unit", "veg_type", "category", "side_dish", "lactose_free", "gluten_free",
            "shelf_life_days", "kcal", "protein", "carbs", "fat")


def _save(doc):
    """Gleiches Format wie die Website (YamlEditor.INGREDIENT_FIELDS)."""
    yr.update_yaml(INGREDIENTS_YAML, "ingredients", [yr.normalize_ingredient(i) for i in doc.get("ingredients", [])])


def _apply(target: dict, args) -> None:
    if args.veg_type is not None and args.veg_type not in VALID_VEG:
        raise SystemExit(f"veg_type must be one of {sorted(VALID_VEG)}")
    if args.category is not None and args.category not in yr.INGREDIENT_CATEGORIES:
        raise SystemExit(f"category must be one of {list(yr.INGREDIENT_CATEGORIES)}")
    for key in EDITABLE:
        value = getattr(args, key, None)
        if value is not None:
            target[key] = value


def add_cmd(args,doc):

    new_id = next_ing_id(doc)
    rec = {"ingredient_id": new_id}
    _apply(rec, args)
    doc.setdefault("ingredients", []).append(rec)
    _save(doc)
    print(f"OK: added ingredient_id={new_id} ({args.name})")

def edit_cmd(args,doc):

    arr = doc.get("ingredients", [])
    target = None
    for r in arr:
        if int(r.get("ingredient_id", -1)) == int(args.id):
            target = r; break
    if not target:
        raise SystemExit(f"ingredient_id={args.id} not found")

    _apply(target, args)   # nur angegebene Felder aendern
    _save(doc)
    print(f"OK: updated ingredient_id={args.id}")

def list_cmd(args,doc):

    for r in doc.get("ingredients", []):
        r = yr.normalize_ingredient(r)
        print(f"{r['ingredient_id']:>4}  {r['name'] or '(no name)'}  {r['veg_type'] or '-'}  {r['category']}  "
              f"unit={r['unit'] or '-'}  kcal={r['kcal']}  protein={r['protein']}")

def main(argv=None):
    #   python    script.py - -ingredients    ingredients.yaml     add - -name    "Tomate" - -veg - type    vegan - -side - dish    true

    doc =  yr.load_yaml(INGREDIENTS_YAML)
    p = argparse.ArgumentParser(description="Add or edit ingredients.") ## Wenn Man Help Eingegibt  python    script.py --help


    sub = p.add_subparsers(dest="cmd", required=True)

    def fields(parser, required):
        parser.add_argument("--name", required=required)
        parser.add_argument("--veg-type", required=required)
        parser.add_argument("--category", help="ingredient | basic (Grundzutat) | spice (Gewuerz)")
        parser.add_argument("--side-dish", type=parse_bool, required=required)
        parser.add_argument("--unit", help="Bezugseinheit der Naehrwerte, z.B. g, EL, Stück")
        parser.add_argument("--lactose-free", type=parse_bool)
        parser.add_argument("--gluten-free", type=parse_bool)
        parser.add_argument("--shelf-life-days", type=int)
        for key in ("kcal", "protein", "carbs", "fat"):
            parser.add_argument(f"--{key}", type=float, help="pro --unit")

    pa = sub.add_parser("add", help="Add a new ingredient")
    fields(pa, required=True)
    pa.set_defaults(func=add_cmd)

    pe = sub.add_parser("edit", help="Edit an existing ingredient by id")
    pe.add_argument("--id", type=int, required=True)
    fields(pe, required=False)
    pe.set_defaults(func=edit_cmd)

    pl = sub.add_parser("list", help="List ingredients")
    pl.set_defaults(func=list_cmd)
    args = p.parse_args(argv)
    #Hier Funktion Params Mitgeben
    return args.func(args,doc)

if __name__ == "__main__":
    sys.exit(main())
