import yaml
from pathlib import Path
from flask import Flask, send_from_directory, request, jsonify
from Tools import YamlEditor as yr
from Tools import RatingLogic as rl
from Tools import ProposeLogic as pl
APP_DIR = Path(__file__).parent.resolve()
DATA_DIR = APP_DIR / "server_data"
DATA_DIR.mkdir(exist_ok=True)

# gemeinsame Daten (fuer alle User)
FILES = {
    "ingredients": DATA_DIR / "ingredients.yaml",
    "recipes": DATA_DIR / "recipes.yaml",
    "recipe_ingredients": DATA_DIR / "recipe_ingredients.yaml",
    "wishlist": DATA_DIR / "wishlist.yaml",
    "blacklist": DATA_DIR / "blacklist.yaml",
    "users": DATA_DIR / "users.yaml",
}
# pro User: user_data/user_<id>.yaml mit history + default_ratings (YamlEditor.USER_KEYS)
USER_DIR = DATA_DIR / "user_data"


def _ensure_files():
    """
    Teste ob die Datein Existieren ansonsten erstelle Blanks.
    :return:
    """
    for key, p in FILES.items():
        if not p.exists():
            with p.open("w", encoding="utf-8") as f:
                yaml.safe_dump({ key: [] }, f, sort_keys=False, allow_unicode=True)


def _user_id(raw):
    """user_id aus Request -> als String, wenn es den User in users.yaml gibt, sonst None
    (der Wert landet im Dateinamen - also nur bekannte IDs)."""
    if raw in (None, ""):
        return None
    doc = yr.load_yaml(FILES["users"]) if FILES["users"].exists() else {}
    known = {str(u.get("user_id")) for u in doc.get("users") or []}
    return str(raw) if str(raw) in known else None


def _require_user(raw):
    user = _user_id(raw)
    if user is None:
        raise ValueError("user required (Bitte oben einen User waehlen)")
    return user


def load_all(user_id=None):
    """Gemeinsame Daten + history / default_ratings des Users (ohne gueltigen User: beide leer)."""
    _ensure_files()
    data = {}
    for key, p in FILES.items():
        doc = yr.load_yaml(p)
        # doc.get(key, []) faellt nur bei fehlendem Key auf [] zurueck - eine leere YAML-Liste
        # wird aber je nach Editor auch als "key:" (also null) statt "key: []" gespeichert.
        data[key] = doc.get(key) or []
    user = _user_id(user_id)
    data.update(yr.load_user_file(yr.user_file(USER_DIR, user)) if user else {k: [] for k in yr.USER_KEYS})
    return data


def save_all(data, user_id=None):
    """Schreibt nur die Collections, die in data enthalten sind - creation.html / ingredients.html
    schicken z.B. kein wishlist/blacklist mit, die sollen dabei nicht geleert werden.
    history / default_ratings landen nur mit gueltigem User in dessen Datei."""
    _ensure_files()
    if isinstance(data.get("ingredients"), list):   # jede Zutat im gleichen Format speichern
        data["ingredients"] = [yr.normalize_ingredient(i) for i in data["ingredients"]]
    for key, p in FILES.items():
        if key in data:
            yr.update_yaml(p, key, data[key])
    user = _user_id(user_id)
    if user and any(k in data for k in yr.USER_KEYS):
        path = yr.user_file(USER_DIR, user)
        yr.save_user_file(path, {**yr.load_user_file(path), **{k: data[k] for k in yr.USER_KEYS if k in data}})


def _find_recipe(data, recipe_id):
    return next((r for r in data.get("recipes", []) if r.get("recipe_id") == recipe_id), None)


def _recipe_ingredients(data, recipe_id):
    """Zutatenliste eines Rezepts fuer die Seiten: recipe_ingredients + Name / veg_type aus ingredients.yaml.
    Fehlt eine Zutat in ingredients.yaml, wird sie uebersprungen."""
    ingredients_by_id = {ing.get("ingredient_id"): ing for ing in data.get("ingredients", [])}
    out = []
    for ri in data.get("recipe_ingredients", []):
        ing = ingredients_by_id.get(ri.get("ingredient_id"))
        if ri.get("recipe_id") != recipe_id or not ing:
            continue
        out.append({
            "ingredient_id": ri.get("ingredient_id"),
            "name": ing.get("name"),
            "veg_type": ing.get("veg_type"),
            "quantity": ri.get("quantity"),
            "unit": ri.get("unit"),
        })
    return out


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

@app.get("/dev")
def dev_page():
    return send_from_directory(str(APP_DIR), "dev.html")

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
    """'Nicht interessiert'-Button beim Vorschlag: senkt den Wiederholungswunsch (repeat_rating=0)
    fuer dieses Rezept in der history des Users (siehe RatingLogic.log_dismissed). Braucht einen User."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        user = _require_user(payload.get("user_id"))
        data = load_all(user)
        entry = rl.log_dismissed(data, int(recipe_id))
        save_all(data, user)

        return jsonify({"ok": True, "history_entry": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500 # 500Intern Error

@app.get("/api/all")
def api_get_all():
    """Alle gemeinsamen Daten; mit ?user=<id> auch history / default_ratings dieses Users."""
    try:
        return jsonify(load_all(request.args.get("user")))

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

NO_PROPOSALS_MESSAGE = "Keine passenden Rezepte gefunden - Rezepte durchsuchen oder mit mehr Zufall neu wuerfeln."


def _proposal_response(data, picks, key, t):
    """Vorschlaege fuers Frontend: is_new = noch nie gekocht, message nur wenn die Liste leer ist.
    picks aus ProposeLogic.propose_detailed: source (Herkunft aus der Ziehung), score, replaced (Name)."""
    names = {r.get("recipe_id"): r.get("name") for r in data.get("recipes", [])}
    out = {key: [{**pl.recipe_to_frontend(p["recipe"], is_new=rl.is_new(data, p["recipe"]["recipe_id"])),
                  "source": p["source"], "score": round(p["score"], 2), "wishlist": p["wishlist"],
                  "replaced": names.get(p["replaced"])} for p in picks],
           "t": t}
    if not picks:
        out["message"] = NO_PROPOSALS_MESSAGE
    return out


@app.get("/api/proposals")
def get_default_recipes():
    """GET: Hauptgerichte ohne Filter (Startbildschirm) - Vorschlags-Pipeline ProposeLogic.propose.
    Optional: ?t=<1-10> Zufall (Softmax-Temperatur), ?pool=new nur nie gekochte Rezepte,
    ?allergies=lactose,gluten (YamlEditor.ALLERGENS)."""
    try:
        user = _user_id(request.args.get("user"))
        data = load_all(user)
        t = pl.clamp_t(request.args.get("t", type=float))
        allergies = [a for a in request.args.get("allergies", "").split(",") if a]
        picks = pl.propose_detailed(data, user_id=user, t=t,
                           pool=request.args.get("pool", "all"), allergies=allergies)
        return jsonify(_proposal_response(data, picks, "main_dish", t))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/proposals")
def propose_meal():
    """POST: Gefilterte Rezeptvorschlaege basierend auf Kriterien im Request-Body.
    count Vorschlaege (Standard 10): die ersten werden angezeigt, der Rest ist Puffer fuers Wegklicken.
    t: Zufall 1-10 (Standard ProposeLogic.SOFTMAX_T), pool: "all" | "new" (nur nie gekochte Rezepte),
    allergies: z.B. ["lactose", "gluten"]."""
    try:
        payload = request.get_json(force=True) or {}

        user = _user_id(payload.get("user_id"))
        data = load_all(user)
        t = pl.clamp_t(payload.get("t"))
        picks = pl.propose_detailed(
            data,
            user_id=user,
            meal_type=payload.get("meal_type", "main_dish"),
            diet=payload.get("diet", "any"),
            include=payload.get("include") or [],
            exclude=payload.get("exclude") or [],
            allergies=payload.get("allergies") or [],
            k=int(payload.get("count") or 10),
            t=t,
            pool=payload.get("pool", "all"),
        )
        return jsonify(_proposal_response(data, picks, "recipes", t))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/recipe/suggest")
def api_recipe_suggest():
    """Vorschlaege fuer creation.html (der User muss sie bestaetigen): Hauptzutat, Beilage, Fleischsorten
    und ob das Rezept eine Beilagen-Variante eines bestehenden Rezepts ist.
    Body: {recipe_id (beim Bearbeiten), name, items: [{ingredient_id, quantity, unit}]}"""
    try:
        payload = request.get_json(force=True) or {}
        data = load_all()
        items = payload.get("items") or []
        out = yr.suggest_main_and_side(data, payload.get("name") or "", items)
        out["variant_of"] = yr.side_dish_variant_of(data, payload.get("recipe_id"), items)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/recipe/<int:recipe_id>")
def api_get_recipe(recipe_id):
    user = _user_id(request.args.get("user"))
    data = load_all(user)
    recipes = data.get("recipes", [])
    recipe = _find_recipe(data, recipe_id)
    if recipe is None:
        return jsonify({"error": "recipe not found"}), 404

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
        "ingredients": _recipe_ingredients(data, recipe_id),
        "variants": variants,
        "wishlisted": rl.is_wishlisted(data, recipe_id, user),
        "blacklisted": bool(user) and rl.is_blacklisted(data, recipe_id, user),
        "has_cooked": rl.has_cooked(data, recipe_id),
    })


def _toggle_user_list(toggle):
    """Gemeinsamer Ablauf fuer Wunschliste / Blacklist. Antwort enthaelt beide Zustaende, weil ein
    Rezept nie auf beiden Listen steht (Hinzufuegen nimmt es von der anderen)."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        data = load_all()
        user_id = payload.get("user_id")
        toggle(data, int(recipe_id), user_id)
        save_all(data)

        return jsonify({"ok": True,
                        "wishlisted": rl.is_wishlisted(data, int(recipe_id), user_id),
                        "blacklisted": rl.is_blacklisted(data, int(recipe_id), user_id)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/wishlist/toggle")
def api_wishlist_toggle():
    """'Auf demnaechst setzen'-Button: fuegt das Rezept fuer den User zur Wunschliste
    hinzu bzw. entfernt es wieder (Toggle), gespeichert user-abhaengig in wishlist.yaml."""
    return _toggle_user_list(rl.toggle_wishlist)


@app.post("/api/blacklist/toggle")
def api_blacklist_toggle():
    """'Nicht mehr vorschlagen'-Button: das Rezept wird diesem User nie mehr vorgeschlagen
    (blacklist.yaml, Toggle). Braucht einen User."""
    return _toggle_user_list(rl.toggle_blacklist)


@app.post("/api/history/cooked")
def api_history_cooked():
    """'Einmal gekocht'-Button: schneller Log-Eintrag (nur user_id + Datum, keine Bewertung)."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400

        user = _require_user(payload.get("user_id"))
        data = load_all(user)
        entry = rl.log_cooked(data, int(recipe_id), user)
        save_all(data, user)

        return jsonify({"ok": True, "history_entry": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/rating/<int:recipe_id>")
def api_rating_get(recipe_id):
    """Daten fuer die Bewertungsseite: Rezept + Zutaten + zuletzt gemessene Zeiten,
    damit das Formular sinnvoll vorbefuellt werden kann. ?user=<id> -> Werte dieses Users."""
    try:
        data = load_all(request.args.get("user"))
        recipe = _find_recipe(data, recipe_id)
        if recipe is None:
            return jsonify({"error": "recipe not found"}), 404

        return jsonify({
            "recipe": recipe,
            "ingredients": _recipe_ingredients(data, recipe_id),
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

        user = _require_user(payload.get("user_id"))
        data = load_all(user)
        result = rl.rate_recipe(
            data,
            int(recipe_id),
            user,
            actual_prep=payload.get("actual_prep"),
            actual_cook=payload.get("actual_cook"),
            taste_rating=payload.get("taste_rating"),
            repeat_rating=payload.get("repeat_rating"),
            effort_rating=payload.get("effort_rating"),
            ingredient_overrides=payload.get("ingredient_overrides"),
            save_as_variant=bool(payload.get("save_as_variant")),
            variant_name=payload.get("variant_name"),
        )
        save_all(data, user)

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


@app.get("/api/dev/ratings")
def api_dev_ratings():
    """Entwicklerseite: alle Rezepte mit Status fuer den User - rated (vorab oder echt bewertet),
    die Vorab-Bewertung und ob es schon eine echte Bewertung in der history gibt."""
    try:
        user = _require_user(request.args.get("user"))
        data = load_all(user)
        out = []
        for r in data.get("recipes", []):
            rid = r.get("recipe_id")
            entry = next((h for h in data["history"] if h.get("recipe_id") == rid), {})
            out.append({
                "recipe_id": rid, "name": r.get("name"), "recipe_type": r.get("recipe_type"),
                "veg_type": r.get("veg_type"), "rated": rl.is_rated(data, rid),
                "history_rated": any(v is not None for v in entry.get("taste_rating") or []),
                "default_rating": yr.default_rating(data, rid),
            })
        return jsonify({"recipes": out})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/dev/rating")
def api_dev_rating():
    """Vorab-Bewertung setzen: {user_id, recipe_id, taste_rating, effort_rating, repeat_rating} (0-10 / null,
    alle null = entfernen). Setzt KEIN Kochdatum (anders als /api/rating)."""
    try:
        payload = request.get_json(force=True) or {}
        recipe_id = payload.get("recipe_id")
        if recipe_id is None:
            return jsonify({"error": "recipe_id required"}), 400
        user = _require_user(payload.get("user_id"))
        data = load_all(user)
        entry = rl.set_default_rating(data, int(recipe_id), payload.get("taste_rating"),
                                      payload.get("effort_rating"), payload.get("repeat_rating"))
        save_all({"default_ratings": data["default_ratings"]}, user)
        return jsonify({"ok": True, "default_rating": entry})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
