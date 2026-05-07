
import os, json, yaml
from pathlib import Path
from flask import Flask, send_from_directory, request, jsonify
from Tools import YamlEditor as yr
from Tools.YamlEditor import Ingredient, Recipe, RecipeIngredientLink
APP_DIR = Path(__file__).parent.resolve()
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

FILES = {
    "ingredients": DATA_DIR / "ingredients.yaml",
    "recipes": DATA_DIR / "recipes.yaml",
    "recipe_ingredients": DATA_DIR / "recipe_ingredients.yaml",
    "history": DATA_DIR / "history.yaml",
}
CACHE = {}
def _ensure_files():
    """
    Teste ob die Datein Existieren ansonsten erstelle Blanks.
    :return:
    """
    for key, p in FILES.items():
        if not p.exists():
            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump({ key: [] }, f, sort_keys=False, allow_unicode=True)

def load_all():
    _ensure_files()
    data = {}
    for key, p in FILES.items():
        doc = yr.load_yaml(p)
        data[key] = doc.get(key, [])
    return data

def save_all(data):
    _ensure_files()
    for key, p in FILES.items():
        val = data.get(key, [])
        yr.update_yaml(key, val)


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
@app.get("/api/ping")
def api_ping():
    return jsonify({"ok": True})
@app.post("/api/dismiss")
def ditch_prop():
    try:
        payload = request.get_json(force=True) or {}
        print(payload)
        print("Dissmis Recipe ID:", payload["recipe_id"])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500 # 500Intern Error

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

def recipe_to_frontend(r):
    """Convert recipe dict to frontend format"""
    return {
        "id": r.get("recipe_id"),
        "name": r.get("name"),
        "recipe_type": r.get("recipe_type", "-"),
        "veg_type": r.get("veg_type"),
        "prep_t": r.get("prep_minutes", "0"),
        "cook_t": r.get("cook_minutes", "0"),
    }

@app.get("/api/propsals")
def get_default_recipes():
    """GET: Return default/random recipes without filters"""
    try:
        data = load_all()
        recipes = data.get("recipes", [])
        
        # Convert to frontend format
        mapped = [recipe_to_frontend(r) for r in recipes]
        
        # Filter by type
        main_dish = [r for r in mapped if r.get("recipe_type") == "main_dish"]
        
        # Shuffle and return
        random.shuffle(main_dish)
        
        return jsonify({
            "main_dish": main_dish[:5],  # Return 5 main dishes
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/propsals")
def propose_meal():
    """POST: Return filtered recipes based on user criteria"""
    try:
        payload = request.get_json(force=True) or {}
        
        data = load_all()
        recipes = data.get("recipes", [])
        
        # Apply filters if provided
        meal_type = payload.get("meal_type", "main_dish")
        diet = payload.get("diet", "any")
        include = payload.get("include", [])
        exclude = payload.get("exclude", [])
        
        # Filter recipes
        filtered = []
        for r in recipes:
            # Type filter
            if r.get("recipe_type") != meal_type:
                continue
            # Diet filter
            if diet != "any" and r.get("veg_type") != diet:
                continue
            filtered.append(r)
        
        # Convert to frontend format
        mapped = [recipe_to_frontend(r) for r in filtered]
        random.shuffle(mapped)
        
        return jsonify({
            "recipes": mapped,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/create/<int:recipe_id>")
def api_get_recipe(recipe_id):
    data = load_all()

    recipes = data.get("recipes", [])
    recipe_ingredients = data.get("recipe_ingredients", [])
    ingredients = data.get("ingredients", [])

    #next(iterator, default=None)
    #(r for r in recipes if r.get("recipe_id") == recipe_id) erzeugt Generator der erst auf anfrage einzeln werte Ausgibt
    #deswegen next
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
    CACHE = load_all()
    app.run(host="127.0.0.1", port=5000, debug=True)
