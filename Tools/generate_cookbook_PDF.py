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
sys.path.insert(0, str(APP_DIR))   # Projekt-Root -> "Tools" importierbar (gleiche Standard-Bewertungen wie die App)
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
SEASON_DE = {"all": "Ganzjährig", "always": "Ganzjährig", "spring": "Frühling", "summer": "Sommer",
             "autumn": "Herbst", "winter": "Winter"}
VEG_DE = {"vegan": "Vegan", "vegetarian": "Vegetarisch", "meat": "Fleisch", "fish": "Fisch"}
# Zutatenliste pro Rezept: (category, Ueberschrift, als Aufzaehlung? sonst kompakt in einer Zeile)
INGREDIENT_BLOCKS = [("ingredient", "Zutaten", True), ("basic", "Grundzutaten", False), ("spice", "Gewürze", False)]


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
    """Saison · Typ · Kueche · Methode · Art (Rezeptfelder aus docs/ProposeLogic.md V). Fehlende
    Saison = ganzjaehrig (wie in der App), die uebrigen Felder nur, wenn gepflegt."""
    parts = ["Saison: " + SEASON_DE.get(rec.season or "all", rec.season)]
    if rec.veg_type in VEG_DE:
        parts.append("Typ: " + VEG_DE[rec.veg_type])
    if rec.origin:
        parts.append("Küche: " + ", ".join(ORIGIN_DE.get(o, o) for o in rec.origin))
    if rec.cooking_method:
        parts.append("Methode: " + METHOD_DE.get(rec.cooking_method, rec.cooking_method))
    if rec.recipe_spec:
        parts.append("Art: " + SPEC_DE.get(rec.recipe_spec, rec.recipe_spec))
    return " • ".join(parts)


def score_line(rec: Recipe, entry: Optional[dict]) -> str:
    """Bewertungen: pro Bewertung der Schnitt aus der history, sonst der Standardwert des Rezepts
    (RatingLogic.default_ratings, wie beim Vorbefuellen der Bewertungsseite)."""
    entry = entry or {}
    defaults = rl.default_ratings({"history": [{**entry, "recipe_id": rec.recipe_id}] if entry else []},
                                  rec.recipe_id)
    parts = []
    for key, label in (("taste_rating", "Geschmack"), ("effort_rating", "Aufwand"), ("repeat_rating", "Wiederholen")):
        avg = defaults[f"{key}_avg"]
        value = avg if avg is not None else defaults[key]
        parts.append(f"{label} {fmt_score(value)}/10" + ("" if avg is not None else " (Standard)"))
    return " • ".join(parts)


def ingredient_text(lk: RecipeIngredientLink, ing: Optional[Ingredient], is_main: bool) -> str:
    """'3 EL Sojasauce (Notiz)' als LaTeX, die Hauptzutat fett."""
    name = ing.name if ing else f"Unbekannte Zutat (ID {lk.ingredient_id})"
    note = " (" + lk.note + ")" if lk.note else ""
    left = " ".join(p for p in [fmt_qty(lk.quantity), lk.unit or ""] if p).strip()
    text = lG.latex_escape(name + note)
    if is_main:
        text = r"\textbf{" + text + "}"
    return (lG.latex_escape(left) + " " + text) if left else text





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
            category=yr.normalize_ingredient(inc)["category"],
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
            season=r.get("season"),
            side_dish=(int(r["side_dish"]) if isinstance(r.get("side_dish"), int) else None),
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
    """Zutaten nach veg_type, Grundzutaten und Gewuerze je in einer eigenen Gruppe."""
    buckets = defaultdict(list)
    for ing in ingredients.values():
        if ing.category == "basic":
            key = "grundzutaten"
        elif ing.category == "spice":
            key = "gewürze"
        else:
            key = ing.veg_type or "unknown"
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
            L.append(r"\subsection{" + lG.latex_escape(rec.name) + r"}\label{" + recipe_label(rec) + "}")

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



            # Zutatenliste in Zutaten / Grundzutaten / Gewuerze aufgeteilt, Hauptzutat fett
            by_category = defaultdict(list)
            for lk, ing in recipe_to_ings.get(rec.recipe_id, []):
                by_category[ing.category if ing else "ingredient"].append(
                    ingredient_text(lk, ing, lk.ingredient_id == rec.main_ingredient))
            for category, title, as_list in INGREDIENT_BLOCKS:
                items = by_category.get(category, [])
                if not items and not (category == "ingredient" and not by_category):
                    continue
                L.append(r"\noindent")
                L.append(r"\textbf{" + lG.latex_escape(title) + r":}")
                if as_list:
                    L.append(r"\begin{multicols}{2}")
                    L.append(r"\begin{itemize}")
                    L.extend(r"  \item " + item for item in items or [r"\emph{Keine Zutaten verlinkt.}"])
                    L.append(r"\end{itemize}")
                    L.append(r"\end{multicols}")
                else:
                    L.append("; ".join(items) + r"\\")



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

            # Varianten derselben Familie (gleiches Hauptrezept) verlinken, z.B. mit Reis statt Nudeln
            family = variant_family(rec, recipes)
            if family:
                L.append(r"\noindent")
                L.append(r"\textbf{Varianten:}")
                L.append("; ".join(variant_link(v, ingredients) for v in family) + r"\\")
            L.append("")

    return "\n".join(L).strip() + "\n"


def variant_family(rec: Recipe, recipes: Dict[int, Recipe]) -> List[Recipe]:
    """Alle anderen Rezepte mit demselben Hauptrezept (variant_of), Hauptrezept zuerst."""
    root = rec.variant_of or rec.recipe_id
    family = [r for r in recipes.values()
              if r.recipe_id != rec.recipe_id and (r.recipe_id == root or r.variant_of == root)]
    return sorted(family, key=lambda r: (r.recipe_id != root, r.name.lower()))


def variant_link(rec: Recipe, ingredients: Dict[int, Ingredient]) -> str:
    """Klickbarer Link 'Name (mit Reis, S. 5)' auf das Rezept im PDF."""
    side = ingredients.get(rec.side_dish) if rec.side_dish is not None else None
    extra = ("mit " + side.name + ", ") if side else ""
    return (r"\hyperref[" + recipe_label(rec) + "]{" + lG.latex_escape(rec.name) + "} ("
            + lG.latex_escape(extra) + r"S.~\pageref{" + recipe_label(rec) + "})")


def recipe_label(rec: Recipe) -> str:
    return f"rezept:{rec.recipe_id}"


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
        ("grundzutaten", "Grundzutaten"),
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
