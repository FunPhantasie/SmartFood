#Kommentar
import os, json, yaml
from pathlib import Path
from flask import Flask, send_from_directory, request, jsonify
from Tools import YamlEditor as yr
from Tools import RatingLogic as rl
from Tools import ProposeLogic as pl
from Tools.YamlEditor import Ingredient, Recipe, RecipeIngredientLink
APP_DIR = Path(__file__).parent.resolve()
DATA_DIR = APP_DIR / "server_data"
DATA_DIR.mkdir(exist_ok=True)

FILES = {
    "ingredients": DATA_DIR / "ingredients.yaml",
    "recipes": DATA_DIR / "recipes.yaml",
    "recipe_ingredients": DATA_DIR / "recipe_ingredients.yaml",
    "history": DATA_DIR / "history.yaml",
    "wishlist": DATA_DIR / "wishlist.yaml",
    "users": DATA_DIR / "users.yaml",
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
        # doc.get(key, []) faellt nur bei fehlendem Key auf [] zurueck - eine leere YAML-Liste
        # wird aber je nach Editor auch als "key:" (also null) statt "key: []" gespeichert.
        data[key] = doc.get(key) or []
    return data

def save_all(data):
    _ensure_files()
    for key, p in FILES.items():
        val = data.get(key, [])
        yr.update_yaml(p, key, val)


app = Flask(__name__, static_folder=str(APP_DIR), static_url_path="/static")

@app.get("/")
def index():
    return send_from_directory(str(APP_DIR), "home_find.html")
@app.get("/create")
def recipe_proposer():
    return send_from_directory(str(APP_DIR), "creation.html")

@app.get("/recipe")
def recipe_page():
    return send_from_directory(str(APP_DIR), "recipe.html")

@app.get("/ingredients")
def ingredients_page():
    return send_from_directory(str(APP_DIR), "ingredients.html")

@app.get("/rating")
def rating_page():
    return send_from_directory(str(APP_DIR), "rating.html")

@app.get("/api/ping")
def api_ping():
    return jsonify({"ok": True})

@app.get("/api/users")
def api_get_users():
    """Fester Satz an Usern aus users.yaml, fuer die Navbar-Auswahl."""
    try:
        doc = yr.load_yaml(FILES["users"]) if FILES["users"].exists() else {}
        return jsonify({"users": doc.get("users", [])})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/dismiss")
def ditch_prop():
    """'Nicht interessiert'-Button beim Vorschlag: senkt den Wiederholungswunsch (repeat_rating=1)
    fuer dieses Rezept per neuem history-Eintrag (siehe RatingLogic.log_dismissed)."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        data = load_all()
        entry = rl.log_dismissed(data, int(recipe_id))
        save_all(data)

        return jsonify({"ok": True, "history_entry": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
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

@app.get("/api/propsals")
def get_default_recipes():
    """GET: Zufaellige Hauptgerichte ohne Filter (Startbildschirm)."""
    try:
        data = load_all()
        filtered = pl.filter_recipes(data.get("recipes", []), meal_type="main_dish", diet="any")

        mapped = [pl.recipe_to_frontend(r) for r in filtered]
        scores = rl.recipe_scores(data)
        mapped = rl.weighted_shuffle(mapped, scores, id_key="id")

        return jsonify({
            "main_dish": mapped[:5],  # Return 5 main dishes
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/propsals")
def propose_meal():
    """POST: Gefilterte Rezeptvorschlaege basierend auf Kriterien im Request-Body."""
    try:
        payload = request.get_json(force=True) or {}

        data = load_all()
        filtered = pl.filter_recipes(
            data.get("recipes", []),
            meal_type=payload.get("meal_type", "main_dish"),
            diet=payload.get("diet", "any"),
            include=payload.get("include", []),
            exclude=payload.get("exclude", []),
        )

        mapped = [pl.recipe_to_frontend(r) for r in filtered]
        scores = rl.recipe_scores(data)
        mapped = rl.weighted_shuffle(mapped, scores, id_key="id")

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

    # Andere Rezepte aus der gleichen "Familie" (gleiches Hauptrezept) finden,
    # egal ob das aktuelle Rezept selbst das Haupt ist oder eine Variante.
    main_id = recipe.get("variant_of")
    if main_id is None:
        main_id = recipe.get("recipe_id")

    variants = [
        {"recipe_id": r.get("recipe_id"), "name": r.get("name")}
        for r in recipes
        if r.get("recipe_id") != recipe_id
        and (r.get("recipe_id") == main_id or r.get("variant_of") == main_id)
    ]

    return jsonify({
        "recipe": recipe,
        "ingredients": resolved_ingredients,
        "variants": variants,
        "wishlisted": rl.is_wishlisted(data, recipe_id, request.args.get("user")),
        "has_cooked": rl.has_cooked(data, recipe_id),
    })


@app.post("/api/wishlist/toggle")
def api_wishlist_toggle():
    """'Auf demnaechst setzen'-Button: fuegt das Rezept fuer den User zur Wunschliste
    hinzu bzw. entfernt es wieder (Toggle), gespeichert user-abhaengig in history.yaml."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        data = load_all()
        wishlisted = rl.toggle_wishlist(data, int(recipe_id), payload.get("user_id"))
        save_all(data)

        return jsonify({"ok": True, "wishlisted": wishlisted})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/history/cooked")
def api_history_cooked():
    """'Einmal gekocht'-Button: schneller Log-Eintrag (nur user_id + Datum, keine Bewertung)."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        data = load_all()
        entry = rl.log_cooked(data, int(recipe_id), payload.get("user_id"))
        save_all(data)

        return jsonify({"ok": True, "history_entry": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/rating/<int:recipe_id>")
def api_rating_get(recipe_id):
    """Daten fuer die Bewertungsseite: Rezept + Zutaten + zuletzt gemessene Zeiten,
    damit das Formular sinnvoll vorbefuellt werden kann."""
    try:
        data = load_all()
        recipes = data.get("recipes", [])
        recipe_ingredients = data.get("recipe_ingredients", [])
        ingredients = data.get("ingredients", [])

        recipe = next((r for r in recipes if r.get("recipe_id") == recipe_id), None)
        if recipe is None:
            return jsonify({"error": "recipe not found"}), 404

        ingredients_by_id = {ing.get("ingredient_id"): ing for ing in ingredients}
        resolved_ingredients = []
        for ri in recipe_ingredients:
            if ri.get("recipe_id") != recipe_id:
                continue
            ing = ingredients_by_id.get(ri.get("ingredient_id"))
            if not ing:
                continue
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
            "last_actual_times": rl.last_actual_times(data, recipe_id),
            "default_ratings": rl.default_ratings(data, recipe_id),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/rating")
def api_rating_post():
    """Volle Bewertung ueber 'Gekocht & bewerten' (Zeiten, Geschmack, Wiederholungswunsch,
    optional Zutaten-Abweichung als Ueberschreibung oder neue Variante)."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        data = load_all()
        result = rl.rate_recipe(
            data,
            int(recipe_id),
            payload.get("user_id"),
            actual_prep=payload.get("actual_prep"),
            actual_cook=payload.get("actual_cook"),
            taste_rating=payload.get("taste_rating"),
            repeat_rating=payload.get("repeat_rating"),
            effort_rating=payload.get("effort_rating"),
            ingredient_overrides=payload.get("ingredient_overrides"),
            save_as_variant=bool(payload.get("save_as_variant")),
            variant_name=payload.get("variant_name"),
        )
        save_all(data)

        return jsonify({
            "ok": True,
            "history_entry": result["history_entry"],
            "recipe_id": result["recipe"]["recipe_id"],
            "new_variant": result["new_variant"],
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500




if __name__ == "__main__":
    CACHE = load_all()
    app.run(host="127.0.0.1", port=5000, debug=True)
