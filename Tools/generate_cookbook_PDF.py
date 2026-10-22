#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import shutil
import subprocess
import tempfile
import sys
import re
import YamlEditor as yr
from YamlEditor import Ingredient,Recipe,RecipeIngredientLink
import latexDefaultGenerator as lG
# ------------------------------------------------------------
# Pfade (wie von dir gewünscht)
# ------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))   # Projekt-Root -> "Tools" importierbar (gleiche Score-Formeln wie die App)
from Tools import ProposeLogic as pl  # noqa: E402
from Tools import RatingLogic as rl  # noqa: E402

DATA_DIR = APP_DIR / "Server" / "server_data"   # gleiche Daten wie die Website

RECIPES_YAML = DATA_DIR / "recipes.yaml"
RECIPE_INGREDIENTS_YAML = DATA_DIR / "recipe_ingredients.yaml"
INGREDIENTS_YAML = DATA_DIR / "ingredients.yaml"
HISTORY_YAML = DATA_DIR / "history.yaml"      # optional: Bewertungen -> Scores im PDF

ORIGIN_DE = {"asian": "Asiatisch", "oriental": "Orientalisch", "mexican": "Mexikanisch", "indian": "Indisch",
             "italian": "Italienisch", "home-style": "Hausmannskost", "mediterranean": "Mediterran",
             "american": "Amerikanisch"}
METHOD_DE = {"oven": "Ofen", "pan": "Pfanne", "pot": "Topf", "grill": "Grill", "raw": "Roh", "steam": "Dampf"}
SPEC_DE = {"soup": "Suppe", "salad": "Salat", "casserole": "Auflauf", "bowl": "Bowl",
           "sandwich": "Sandwich", "others": "Sonstiges"}


# ------------------------------------------------------------
# Aufbau PDF
# ------------------------------------------------------------
RECIPE_TYPE_TO_SECTION = {
    "main_dish": "Hauptgerichte",
    "side_dish": "Nebenspeisen",
    "snack": "Snacks",
    "dip": "Dip",
    "sweet": "Süßspeisen",
    "wuerzung": "Gewürzmischungen",
}

SECTION_ORDER = ["Hauptgerichte", "Nebenspeisen", "Snacks", "Dip", "Süßspeisen", "Gewürzmischungen"]








def fmt_qty(q: Optional[float]) -> str:
    """
    Converts Float into String Rounded Format
    :param q:
    :return string:
    """
    if q is None:
        return ""
    if abs(q - round(q)) < 1e-9:
        return str(int(round(q)))
    return str(q).replace(".", ",")


def bool_de(x: Optional[bool]) -> str:
    """
    Turned Bool in Deutsche Sprache
    :param x:
    :return Sprache:
    """
    if x is None:
        return "-"
    return "Ja" if x else "Nein"


def fmt_score(x: float) -> str:
    """Eine Nachkommastelle mit deutschem Komma."""
    return f"{x:.1f}".replace(".", ",")


def info_line(rec: Recipe) -> str:
    """Kueche · Methode · Art (Rezeptfelder aus docs/ProposeLogic.md V), leer wenn nichts gepflegt."""
    parts = []
    if rec.origin:
        parts.append("Küche: " + ", ".join(ORIGIN_DE.get(o, o) for o in rec.origin))
    if rec.cooking_method:
        parts.append("Methode: " + METHOD_DE.get(rec.cooking_method, rec.cooking_method))
    if rec.recipe_spec:
        parts.append("Art: " + SPEC_DE.get(rec.recipe_spec, rec.recipe_spec))
    return " • ".join(parts)


def score_line(rec: Recipe, entry: Optional[dict]) -> str:
    """Bewertungen + reward_score (gleiche Formel wie die App, Tools/ProposeLogic.py).
    Pro Bewertung der Schnitt aus der history, sonst der Standardwert des Rezepts
    (RatingLogic.default_ratings, wie beim Vorbefuellen der Bewertungsseite).
    Datum-/Daempfungs-Scores haengen vom heutigen Tag ab und gehoeren nicht ins gedruckte Buch."""
    entry = entry or {}
    defaults = rl.default_ratings({"history": [{**entry, "recipe_id": rec.recipe_id}] if entry else []},
                                  rec.recipe_id)
    parts = []
    for key, label in (("taste_rating", "Geschmack"), ("effort_rating", "Aufwand"), ("repeat_rating", "Wiederholen")):
        avg = defaults[f"{key}_avg"]
        value = avg if avg is not None else defaults[key]
        parts.append(f"{label} {fmt_score(value)}/10" + ("" if avg is not None else " (Standard)"))
    if entry.get("last_date"):
        cooked = len(set(entry.get("dates") or [])) or 1
        last = date.fromisoformat(entry["last_date"]).strftime("%d.%m.%Y")
        parts.append(f"{cooked}x gekocht (zuletzt {last})")
    else:
        parts.append("noch nie gekocht")
    times = {"prep_minutes": rec.prep_minutes, "cook_minutes": rec.cook_minutes}
    reward = pl.reward_score(times, entry)
    if reward is not None:
        parts.append(f"Reward {fmt_score(reward)}/10")
    return " • ".join(parts)





# ------------------------------------------------------------
# Parser
# ------------------------------------------------------------
def parse_ingredients(doc: dict) -> Dict[int, Ingredient]:
    items = doc.get("ingredients", []) or []
    out: Dict[int, Ingredient] = {}
    for inc in items:
        try:
            iid = int(inc.get("ingredient_id"))
        except Exception:
            continue
        out[iid] = Ingredient(
            ingredient_id=iid,
            name=str(inc.get("name", "")).strip(),
            veg_type=(str(inc.get("veg_type")).strip() if inc.get("veg_type") is not None else None),
            spice =(bool(inc.get("spice")) if inc.get("spice") is not None else None),

        )

    return out


def parse_recipes(doc: dict) -> Dict[int, Recipe]:
    items = doc.get("recipes", []) or []
    out: Dict[int, Recipe] = {}
    for r in items:
        try:
            rid = int(r.get("recipe_id"))
        except Exception:
            continue

        veg = str(r.get("veg_type", "")).strip() or "unknown"
        recipe_type = (str(r.get("recipe_type")).strip() if r.get("recipe_type") is not None else None)
        origin = r.get("origin") or []

        out[rid] = Recipe(
            recipe_id=rid,
            name=str(r.get("name", "")).strip(),
            veg_type=veg,
            cook_minutes=(int(r["cook_minutes"]) if r.get("cook_minutes") is not None else None),
            prep_minutes=(int(r["prep_minutes"]) if r.get("prep_minutes") is not None else None),
            sweet=(bool(r.get("sweet")) if r.get("sweet") is not None else None),
            instructions=(str(r.get("instructions")).strip() if r.get("instructions") is not None else None),
            variant_of=(int(r["variant_of"]) if r.get("variant_of") not in (None, "", "null") else None),
            recipe_type=recipe_type,
            origin=tuple(origin if isinstance(origin, list) else [origin]),
            cooking_method=r.get("cooking_method"),
            recipe_spec=r.get("recipe_spec"),
            main_ingredient=r.get("main_ingredient"),
        )
    return out


def parse_history(doc: dict) -> Dict[int, dict]:
    """Genau ein history-Eintrag pro Rezept (siehe RatingLogic)."""
    return {h.get("recipe_id"): h for h in doc.get("history", []) or []}


def parse_links(doc: dict) -> List[RecipeIngredientLink]:
    items = doc.get("recipe_ingredients", []) or []
    out: List[RecipeIngredientLink] = []
    for r in items:
        try:
            rid = int(r.get("recipe_id"))
            iid = int(r.get("ingredient_id"))
        except Exception:
            continue
        qty = None
        if r.get("quantity") is not None:
            try:
                qty = float(r.get("quantity"))
            except Exception:
                qty = None
        unit = (str(r.get("unit")).strip() if r.get("unit") is not None else None)
        note = (str(r.get("note")).strip() if r.get("note") is not None else None)

        out.append(RecipeIngredientLink(recipe_id=rid, ingredient_id=iid, quantity=qty, unit=unit,note=note))
    return out


# ------------------------------------------------------------
# Strukturieren
# ------------------------------------------------------------
def build_recipe_to_ingredients(    links: List[RecipeIngredientLink],    ingredients_by_id: Dict[int, Ingredient],) -> Dict[int, List[Tuple[RecipeIngredientLink, Optional[Ingredient]]]]:
    #Arrows means OUtput
    out: Dict[int, List[Tuple[RecipeIngredientLink, Optional[Ingredient]]]] = {}
    for lk in links:
        ing = ingredients_by_id.get(lk.ingredient_id)
        out.setdefault(lk.recipe_id, []).append((lk, ing))
    for rid, arr in out.items():
        arr.sort(key=lambda t: ((t[1].name.lower() if t[1] else "zzz"), t[0].ingredient_id))
    return out


def infer_section(recipe: Recipe) -> str:
    rt = (recipe.recipe_type or "").strip().lower()
    return RECIPE_TYPE_TO_SECTION.get(rt, "Hauptgerichte")


def group_recipes_by_section(recipes: Dict[int, Recipe]) -> Dict[str, List[Recipe]]:
    groups: Dict[str, List[Recipe]] = {}
    for rec in recipes.values():
        sec = infer_section(rec)
        groups.setdefault(sec, []).append(rec)
    for k in groups:
        groups[k].sort(key=lambda r: (r.name.lower(), r.recipe_id))
    return groups
def group_ingredients_by_veg_type(ingredients):
    buckets = defaultdict(list)
    for ing in ingredients.values():
        if not ing.spice:
           key = ing.veg_type or "unknown"
        else:
            key = "gewürze"
        buckets[key].append(ing)
    return buckets

# ------------------------------------------------------------
# LaTeX Inhalt erzeugen (für <<CONTENT>>)
# ------------------------------------------------------------
def generate_content(
    recipes: Dict[int, Recipe],
    ingredients: Dict[int, Ingredient],
    links: List[RecipeIngredientLink],
    history: Optional[Dict[int, dict]] = None,
) -> str:
    history = history or {}
    groups = group_recipes_by_section(recipes)
    recipe_to_ings = build_recipe_to_ingredients(links, ingredients)

    L: List[str] = []

    for section in SECTION_ORDER:
        recs = groups.get(section, [])
        L.append(r"\section{" + lG.latex_escape(section) + r"}")
        L.append("")
        if not recs:
            L.append(r"\emph{(noch keine Rezepte in dieser Kategorie)}")
            L.append("")
            continue

        for rec in recs:
            L.append(r"\subsection{" + lG.latex_escape(rec.name) + r"}")

            # optional: Meta anzeigen (ohne Sortierwirkung)
            meta = []
            if rec.prep_minutes is not None:
                meta.append(f"Vorbereitungszeit: {rec.prep_minutes} min")
            if rec.cook_minutes is not None:
                meta.append(f"Kochzeit: {rec.cook_minutes} min")
            #if rec.variant_of is not None:
            #    meta.append(f"Variante von ID: {rec.variant_of}")
            if meta:
                L.append(r"\textit{" + lG.latex_escape(" • ".join(meta)) + r"}\\")
            for line in (info_line(rec), score_line(rec, history.get(rec.recipe_id))):
                if line:
                    L.append(r"\textit{" + lG.latex_escape(line) + r"}\\")
            L.append("")



            normal_ings = []
            spices = []

            ings = recipe_to_ings.get(rec.recipe_id, [])
            if ings:
                for lk, ing in ings:
                    if ing and ing.spice:
                        spices.append((lk, ing))
                    else:
                        normal_ings.append((lk, ing))
            # Zutaten
            L.append(r"\noindent")
            L.append(r"\textbf{Zutaten:}")
            L.append(r"\begin{multicols}{2}")
            L.append(r"\begin{itemize}")
            if normal_ings:
                ##sortbySpices
                for lk, ing in normal_ings:

                    ing_name = ing.name if ing else f"Unbekannte Zutat (ID {lk.ingredient_id})"

                    note= " ("+lk.note+")" if lk.note else ""
                    qty = fmt_qty(lk.quantity)
                    unit = lk.unit or ""
                    left = " ".join([p for p in [qty, unit] if p]).strip()
                    if left:
                        L.append(r"  \item " + lG.latex_escape(left) + " " + lG.latex_escape(ing_name+note))
                    else:
                        L.append(r"  \item " + lG.latex_escape(ing_name+note))
            else:
                L.append(r"  \item \emph{Keine Zutaten verlinkt.}")
            L.append(r"\end{itemize}")
            L.append(r"\end{multicols}")
            if spices:
                L.append(r"\noindent")
                L.append(r"\textbf{Gewürze:}")


                for lk, ing in spices:

                    ing_name = ing.name if ing else f"Unbekanntes Gewürz (ID {lk.ingredient_id})"

                    note= " ("+lk.note+")" if lk.note else ""
                    qty = fmt_qty(lk.quantity)
                    unit = lk.unit or ""
                    left = " ".join([p for p in [qty, unit] if p]).strip()
                    if left:
                        L.append(r"" + lG.latex_escape(left) + " " + lG.latex_escape(ing_name+note)+";  ")
                    else:
                        L.append(r"" + lG.latex_escape(ing_name+note)+";  ")
                L.append((r"\\"))



            if rec.instructions is not None:
                L.append(r"\noindent")
                L.append(r"\textbf{Anleitung}\\")
                instr = (rec.instructions).strip()

                for para in instr.splitlines():
                    para = para.strip()
                    if para:
                        L.append(lG.latex_escape(para) + r"\\")
                    else:
                        L.append(r"\vspace{4pt}")
            L.append("")

    return "\n".join(L).strip() + "\n"


def generate_ingredient_appendix(ingredients, links, onlyUsed=True):
    L: List[str] = []

    L.append(r"\appendix")
    L.append(r"\section{Zutatenübersicht}")
    L.append("")

    if onlyUsed:
        used_ingredient_ids = {lk.ingredient_id for lk in links}
        ingredients = {
            iid: ing
            for iid, ing in ingredients.items()
            if iid in used_ingredient_ids
        }

    buckets = group_ingredients_by_veg_type(ingredients)

    ORDER = [
        ("vegan", "Vegan"),
        ("vegetarian", "Vegetarisch"),
        ("meat", "Fleisch"),
        ("fish", "Fisch"),
        ("gewürze", "Gewürze"),
    ]
    # unbekannte veg_types nicht verschlucken - jede benutzte Zutat soll im Anhang stehen
    ORDER += [(k, k.capitalize()) for k in sorted(buckets) if k not in dict(ORDER)]

    for key, title in ORDER:
        items = buckets.get(key, [])
        if not items:
            continue

        items = sorted(items, key=lambda ing: ing.name.lower())

        L.append(r"\subsection{" + lG.latex_escape(title) + r"}")
        L.append("")
        L.append(r"\begin{multicols}{3}")
        L.append(r"\begin{itemize}")

        for ing in items:
            L.append(r"  \item " + lG.latex_escape(ing.name))

        L.append(r"\end{itemize}")
        L.append(r"\end{multicols}")
        L.append("")

    return "\n".join(L)



def main(argv: Optional[List[str]] = None) -> int:
    # Default-Metadaten (werden ins Template eingesetzt)
    TITLE = "Kochbuch"
    SUBTITLE = "Was nicht brennt, ist kalt."
    AUTHOR = "Tim"
    DATE_STR = None  # None => heutiges Datum


    recipes_doc = yr.load_yaml(RECIPES_YAML)
    links_doc = yr.load_yaml(RECIPE_INGREDIENTS_YAML)
    ingredients_doc = yr.load_yaml(INGREDIENTS_YAML)

    recipes = parse_recipes(recipes_doc)
    ingredients = parse_ingredients(ingredients_doc)
    links = parse_links(links_doc)
    history = parse_history(yr.load_yaml(HISTORY_YAML)) if HISTORY_YAML.exists() else {}

    content = generate_content(recipes, ingredients, links, history)
    appendix = generate_ingredient_appendix(ingredients,links)

    lG.GenerateBody(TITLE=TITLE, SUBTITLE=SUBTITLE, AUTHOR=AUTHOR, DATE_STR=DATE_STR,content=content,appendix=appendix)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
