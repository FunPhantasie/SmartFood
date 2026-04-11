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

import yaml

# ------------------------------------------------------------
# Pfade (wie von dir gewünscht)
# ------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

RECIPES_YAML = DATA_DIR / "recipes.yaml"
RECIPE_INGREDIENTS_YAML = DATA_DIR / "recipe_ingredients.yaml"
INGREDIENTS_YAML = DATA_DIR / "ingredients.yaml"

# Template + Assets (aus deinem LaTeX-Layout)
TEMPLATE_TEX = APP_DIR / "template.tex"      # dein LaTeX-Template (mit Platzhaltern optional)
ASSETS_DIR = APP_DIR / "Bilder"              # enthält z.B. background.pdf, logo_1.png, ...

# Output: nur PDF
OUTPUT_PDF = APP_DIR / "Kochbuch.pdf"

# Default-Metadaten (werden ins Template eingesetzt)
TITLE = "Kochbuch"
SUBTITLE = "Was nicht brennt, ist kalt."
AUTHOR = "Tim"
DATE_STR = None  # None => heutiges Datum

# ------------------------------------------------------------
# Kategorien aus deiner DB (recipe_type)
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


# ------------------------------------------------------------
# Datenklassen
# ------------------------------------------------------------
@dataclass(frozen=True)
class Ingredient:
    ingredient_id: int
    name: str
    veg_type: Optional[str]
    unit: Optional[str]


@dataclass(frozen=True)
class Recipe:
    recipe_id: int
    name: str
    veg_type: str
    cook_minutes: Optional[int]
    prep_minutes: Optional[int]
    sweet: Optional[bool]         # Flag (süß ja/nein), NICHT die Kategorie
    instructions: Optional[str]
    variant_of: Optional[int]
    recipe_type: str    # main_dish, sweet, dip, wuerzung, side_dish, snack


@dataclass(frozen=True)
class RecipeIngredientLink:
    recipe_id: int
    ingredient_id: int
    quantity: Optional[float]
    unit: Optional[str]


# ------------------------------------------------------------
# Utils
# ------------------------------------------------------------
def latex_escape(s: str) -> str:
    if s is None:
        return ""
    rep = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(rep.get(ch, ch) for ch in str(s))


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Fehlende Datei: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fmt_qty(q: Optional[float]) -> str:
    if q is None:
        return ""
    if abs(q - round(q)) < 1e-9:
        return str(int(round(q)))
    return str(q).replace(".", ",")


def bool_de(x: Optional[bool]) -> str:
    if x is None:
        return "-"
    return "Ja" if x else "Nein"


def german_date_str() -> str:
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember"
    ]
    d = date.today()
    return f"{d.day}. {months[d.month-1]} {d.year}"


# ------------------------------------------------------------
# Parser
# ------------------------------------------------------------
def parse_ingredients(doc: dict) -> Dict[int, Ingredient]:
    items = doc.get("ingredients", []) or []
    out: Dict[int, Ingredient] = {}
    for r in items:
        try:
            iid = int(r.get("ingredient_id"))
        except Exception:
            continue
        out[iid] = Ingredient(
            ingredient_id=iid,
            name=str(r.get("name", "")).strip(),
            veg_type=(str(r.get("veg_type")).strip() if r.get("veg_type") is not None else None),
            unit=(str(r.get("unit")).strip() if r.get("unit") is not None else None),
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
        )
    return out


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
        out.append(RecipeIngredientLink(recipe_id=rid, ingredient_id=iid, quantity=qty, unit=unit))
    return out


# ------------------------------------------------------------
# Strukturieren
# ------------------------------------------------------------
def build_recipe_to_ingredients(
    links: List[RecipeIngredientLink],
    ingredients_by_id: Dict[int, Ingredient],
) -> Dict[int, List[Tuple[RecipeIngredientLink, Optional[Ingredient]]]]:
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
) -> str:
    groups = group_recipes_by_section(recipes)
    recipe_to_ings = build_recipe_to_ingredients(links, ingredients)

    L: List[str] = []

    for section in SECTION_ORDER:
        recs = groups.get(section, [])
        L.append(r"\section{" + latex_escape(section) + r"}")
        L.append("")
        if not recs:
            L.append(r"\emph{(noch keine Rezepte in dieser Kategorie)}")
            L.append("")
            continue

        for rec in recs:
            L.append(r"\subsection{" + latex_escape(rec.name) + r"}")

            # optional: Meta anzeigen (ohne Sortierwirkung)
            meta = []
            if rec.prep_minutes is not None:
                meta.append(f"Vorbereitungszeit: {rec.prep_minutes} min")
            if rec.cook_minutes is not None:
                meta.append(f"Kochzeit: {rec.cook_minutes} min")
            #if rec.variant_of is not None:
            #    meta.append(f"Variante von ID: {rec.variant_of}")
            if meta:
                L.append(r"\textit{" + latex_escape(" • ".join(meta)) + r"}\\")
            else:
                pass
            L.append("")

            # Zutaten
            L.append(r"\noindent")
            L.append(r"\textbf{Zutaten:}")
            L.append(r"\begin{multicols}{2}")
            L.append(r"\begin{itemize}")

            ings = recipe_to_ings.get(rec.recipe_id, [])
            if ings:
                for lk, ing in ings:
                    ing_name = ing.name if ing else f"Unbekannte Zutat (ID {lk.ingredient_id})"
                    qty = fmt_qty(lk.quantity)
                    unit = lk.unit or ""
                    left = " ".join([p for p in [qty, unit] if p]).strip()
                    if left:
                        L.append(r"  \item " + latex_escape(left) + " " + latex_escape(ing_name))
                    else:
                        L.append(r"  \item " + latex_escape(ing_name))
            else:
                L.append(r"  \item \emph{Keine Zutaten verlinkt.}")

            L.append(r"\end{itemize}")
            L.append(r"\end{multicols}")

            if rec.instructions is not None:
                L.append(r"\noindent")
                L.append(r"\textbf{Anleitung}\\")
                instr = (rec.instructions).strip()

                for para in instr.splitlines():
                    para = para.strip()
                    if para:
                        L.append(latex_escape(para) + r"\\")
                    else:
                        L.append(r"\vspace{4pt}")
            L.append("")

    return "\n".join(L).strip() + "\n"

def generate_ingredient_appendix(ingredients):
    L: List[str] = []

    L.append(r"\appendix")
    L.append(r"\section{Zutatenübersicht}")
    L.append("")

    buckets = group_ingredients_by_veg_type(ingredients)

    # gewünschte Reihenfolge + hübsche Namen
    ORDER = [
        ("vegan", "Vegan"),
        ("vegetarian", "Vegetarisch"),
        ("meat", "Fleisch"),
    ]

    for key, title in ORDER:
        items = buckets.get(key, [])
        if not items:
            continue

        # alphabetisch innerhalb der Kategorie
        items = sorted(items, key=lambda ing: ing.name.lower())

        L.append(r"\subsection{" + latex_escape(title) + r"}")
        L.append("")

        L.append(r"\begin{multicols}{3}")
        L.append(r"\begin{itemize}")

        for ing in items:
            parts = [ing.name]

            meta = []
            if ing.unit:
                meta.append(f"Einheit: {ing.unit}")


            if meta:
                parts.append("(" + ", ".join(meta) + ")")

            L.append(r"  \item " + latex_escape(" ".join(parts)))

        L.append(r"\end{itemize}")
        L.append(r"\end{multicols}")
        L.append("")

    return "\n".join(L)



# ------------------------------------------------------------
# Template füllen (verhindert doppelte Sections)
# ------------------------------------------------------------
def fill_template(template_text: str, *, title: str, subtitle: str, author: str, date_str: str, content: str) -> str:
    """
    Priorität:
    1) Wenn <<CONTENT>> existiert: dort einfügen.
    2) Sonst: Wenn Template bereits Sections enthält (z.B. \section{Hauptgerichte} ... \appendix),
       dann ersetzen wir den Block von erster Kochbuch-\section bis \appendix durch content.
    3) Fallback: vor \appendix (oder vor \end{document}) einfügen.
    """
    filled = template_text

    filled = filled.replace("<<TITLE>>", latex_escape(title))
    filled = filled.replace("<<SUBTITLE>>", latex_escape(subtitle))
    filled = filled.replace("<<AUTHOR>>", latex_escape(author))
    filled = filled.replace("<<DATE>>", latex_escape(date_str))

    # 1) expliziter Platzhalter
    if "<<CONTENT>>" in filled:
        return filled.replace("<<CONTENT>>", content)

    # 2) Template enthält schon Sections -> Block ersetzen
    appendix_marker = r"\appendix"
    first_sec_pat = r"\\section\{(?:Hauptgerichte|Nebenspeisen|Snacks|Dip|Süßspeisen|Süßspeisen|Gewürzmischungen|Gewuerzmischungen)\}"
    m1 = re.search(first_sec_pat, filled)
    m2 = re.search(re.escape(appendix_marker), filled)
    if m1 and m2 and m1.start() < m2.start():
        return filled[:m1.start()] + content + "\n" + filled[m2.start():]

    # 3) fallback: vor appendix
    if appendix_marker in filled:
        return filled.replace(appendix_marker, content + "\n" + appendix_marker, 1)

    enddoc = r"\end{document}"
    if enddoc in filled:
        return filled.replace(enddoc, content + "\n" + enddoc, 1)

    return filled + "\n" + content + "\n"


# ------------------------------------------------------------
# PDF Build (nur PDF, .tex wird NICHT behalten)
# ------------------------------------------------------------
def compile_to_pdf(tex_content: str, out_pdf: Path) -> None:
    latexmk = shutil.which("latexmk")
    pdflatex = shutil.which("pdflatex")

    if not latexmk and not pdflatex:
        raise RuntimeError(
            "Kein LaTeX-Compiler gefunden. Installiere TeX Live (inkl. latexmk) "
            "oder mindestens pdflatex."
        )

    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="kochbuch_build_") as td:
        td_path = Path(td)

        # Assets rüberkopieren (Bilder/)
        if ASSETS_DIR.exists() and ASSETS_DIR.is_dir():
            shutil.copytree(ASSETS_DIR, td_path / ASSETS_DIR.name)

            # Fallback: zusätzlich ins Root kopieren (falls \graphicspath spinnt)
            for p in ASSETS_DIR.iterdir():
                if p.is_file():
                    shutil.copy2(p, td_path / p.name)

        # Zusätzlich: Falls Assets direkt im Projekt-Root liegen
        for name in ("logo_1.png", "background.pdf"):
            src = APP_DIR / name
            if src.exists() and src.is_file():
                shutil.copy2(src, td_path / name)

        tex_path = td_path / "Kochbuch.tex"
        tex_path.write_text(tex_content, encoding="utf-8")

        if latexmk:
            cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
            res = subprocess.run(cmd, cwd=td, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if res.returncode != 0:
                raise RuntimeError("latexmk fehlgeschlagen:\n" + res.stdout)
        else:
            for _ in range(2):
                cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
                res = subprocess.run(cmd, cwd=td, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if res.returncode != 0:
                    raise RuntimeError("pdflatex fehlgeschlagen:\n" + res.stdout)

        built_pdf = td_path / "Kochbuch.pdf"
        if not built_pdf.exists():
            built_pdf = td_path / (tex_path.stem + ".pdf")
        if not built_pdf.exists():
            raise RuntimeError("PDF wurde nicht erzeugt (unerwartet).")

        shutil.copyfile(built_pdf, out_pdf)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Erzeugt Kochbuch-PDF aus YAML + LaTeX-Template.")
    ap.add_argument("--title", default=TITLE)
    ap.add_argument("--subtitle", default=SUBTITLE)
    ap.add_argument("--author", default=AUTHOR)
    ap.add_argument("--date", default=DATE_STR, help="Datum (String). Default: heutiges Datum.")
    ap.add_argument("--output", default=str(OUTPUT_PDF), help="Pfad zur Output-PDF.")
    ap.add_argument("--template", default=str(TEMPLATE_TEX), help="Pfad zum template.tex")
    args = ap.parse_args(argv)

    recipes_doc = load_yaml(RECIPES_YAML)
    links_doc = load_yaml(RECIPE_INGREDIENTS_YAML)
    ingredients_doc = load_yaml(INGREDIENTS_YAML)

    recipes = parse_recipes(recipes_doc)
    ingredients = parse_ingredients(ingredients_doc)
    links = parse_links(links_doc)

    content = generate_content(recipes, ingredients, links)
    appendix = generate_ingredient_appendix(ingredients)

    template_path = Path(args.template)
    if not template_path.exists():
        raise FileNotFoundError(f"Template nicht gefunden: {template_path}")
    template_text = template_path.read_text(encoding="utf-8")

    date_str = args.date if args.date else german_date_str()
    tex = fill_template(
        template_text,
        title=args.title,
        subtitle=args.subtitle,
        author=args.author,
        date_str=date_str,
        content=content+ "\n" + appendix,
    )

    out_pdf = Path(args.output)
    compile_to_pdf(tex, out_pdf)

    print(f"Fertig. PDF gespeichert unter:\n  {out_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
