
import os, json, yaml
from pathlib import Path
from flask import Flask, send_from_directory, request, jsonify

APP_DIR = Path(__file__).parent.resolve()
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

FILES = {
    "ingredients": DATA_DIR / "ingredients.yaml",
    "recipes": DATA_DIR / "recipes.yaml",
    "recipe_ingredients": DATA_DIR / "recipe_ingredients.yaml",
    "history": DATA_DIR / "history.yaml",
}

def _ensure_files():
    for key, p in FILES.items():
        if not p.exists():
            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump({ key: [] }, f, sort_keys=False, allow_unicode=True)

def load_all():
    _ensure_files()
    data = {}
    for key, p in FILES.items():
        with p.open("r", encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        data[key] = doc.get(key, [])
    return data

def save_all(payload):
    _ensure_files()
    for key, p in FILES.items():
        val = payload.get(key, [])
        with p.open("w", encoding="utf-8") as f:
            yaml.safe_dump({ key: val if isinstance(val, list) else [] }, f, sort_keys=False, allow_unicode=True)

app = Flask(__name__, static_folder=str(APP_DIR))

@app.get("/")
def index():
    return send_from_directory(str(APP_DIR), "home_find.html")
@app.get("/create")
def recipe_proposer():
    return send_from_directory(str(APP_DIR), "creation.html")
@app.get("/recipe")
def recipe_page():
    return send_from_directory(str(APP_DIR), "recipe.html")
@app.get("/api/all")
def api_get_all():
    try:
        return jsonify(load_all())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/all")
def api_post_all():
    try:
        payload = request.get_json(force=True) or {}
        save_all(payload)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import random

@app.get("/api/defaults")
def api_defaults():
    data = load_all()
    recipes = data.get("recipes", [])

    # Frontend erwartet: id, name, meal_type, diet_hint, minutes
    def to_frontend(r):
        return {
            "id": r.get("recipe_id"),
            "name": r.get("name"),
            "recipe_type": r.get("recipe_type","-"),
            "veg_type": r.get("veg_type"),
            "prep_t": r.get("prep_minutes","0"),
            "cook_t": r.get("cook_minutes","0"),
        }

    mapped = [to_frontend(r) for r in recipes]

    main_dish  = [r for r in mapped if r.get("recipe_type") == "main_dish"]
    snack = [r for r in mapped if r.get("recipe_type") == "snack"]

    # Fallback: wenn du noch keine Snacks pflegst
    if not snack:
        snack = []

    random.shuffle(main_dish)
    random.shuffle(snack)

    return jsonify({
        "main_dish": main_dish[:3],
        "snack": snack[:3],
    })

@app.get("/api/create/<int:recipe_id>")
def api_get_recipe(recipe_id):
    data = load_all()

    recipes = data.get("recipes", [])
    recipe_ingredients = data.get("recipe_ingredients", [])
    ingredients = data.get("ingredients", [])

    recipe = next(
        (r for r in recipes if r.get("recipe_id") == recipe_id),
        None
    )
    if recipe is None:
        return jsonify({"error": "recipe not found"}), 404

    # 🔑 Ingredient lookup
    ingredients_by_id = {
        ing.get("ingredient_id"): ing
        for ing in ingredients
    }

    # 🔗 Join recipe_ingredients ↔ ingredients
    resolved_ingredients = []
    for ri in recipe_ingredients:
        if ri.get("recipe_id") != recipe_id:
            continue

        ing = ingredients_by_id.get(ri.get("ingredient_id"))
        if not ing:
            continue  # Ingredient fehlt im YAML → überspringen

        resolved_ingredients.append({
            "ingredient_id": ri.get("ingredient_id"),
            "name": ing.get("name"),
            "veg_type": ing.get("veg_type"),
            "quantity": ri.get("quantity"),
            "unit": ri.get("unit"),
        })

    return jsonify({
        "recipe": recipe,
        "ingredients": resolved_ingredients,
    })
@app.get("/api/recipe/<int:recipe_id>")
def api_get_recipe1(recipe_id):
    data = load_all()

    recipes = data.get("recipes", [])
    recipe_ingredients = data.get("recipe_ingredients", [])
    ingredients = data.get("ingredients", [])

    recipe = next(
        (r for r in recipes if r.get("recipe_id") == recipe_id),
        None
    )
    if recipe is None:
        return jsonify({"error": "recipe not found"}), 404

    # 🔑 Ingredient lookup
    ingredients_by_id = {
        ing.get("ingredient_id"): ing
        for ing in ingredients
    }

    # 🔗 Join recipe_ingredients ↔ ingredients
    resolved_ingredients = []
    for ri in recipe_ingredients:
        if ri.get("recipe_id") != recipe_id:
            continue

        ing = ingredients_by_id.get(ri.get("ingredient_id"))
        if not ing:
            continue  # Ingredient fehlt im YAML → überspringen

        resolved_ingredients.append({
            "ingredient_id": ri.get("ingredient_id"),
            "name": ing.get("name"),
            "veg_type": ing.get("veg_type"),
            "quantity": ri.get("quantity"),
            "unit": ri.get("unit"),
        })

    return jsonify({
        "recipe": recipe,
        "ingredients": resolved_ingredients,
    })






if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
