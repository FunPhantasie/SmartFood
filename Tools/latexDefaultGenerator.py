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




APP_DIR= Path(__file__).resolve().parent.parent
# Template + Assets (aus deinem LaTeX-Layout)
TEMPLATE_TEX = APP_DIR / "Tools/template_latex.tex"      # dein LaTeX-Template (mit Platzhaltern optional)
ASSETS_DIR = APP_DIR / "Bilder"              # enthält z.B. background.pdf, logo_1.png, ...

# Output: nur PDF
OUTPUT_PDF = APP_DIR / "Kochbuch.pdf"



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

def german_date_str() -> str:
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember"
    ]
    d = date.today()
    return f"{d.day}. {months[d.month-1]} {d.year}"


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

def compile_to_pdf(tex_content: str, out_pdf: Path) -> None:
    latexmk = shutil.which("latexmk")
    pdflatex = shutil.which("pdflatex")

    if not latexmk:
        raise RuntimeError(
            "Kein LaTeX-Compiler gefunden. Installiere TeX Live (inkl. latexmk) "
            "oder mindestens pdflatex."
        )
    if not pdflatex:
        raise RuntimeError(
            "Kein LaTeX-Compiler gefunden. Installiere TeX Live (inkl. pdflatex)."
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


def GenerateBody(TITLE, SUBTITLE, AUTHOR, DATE_STR,content,appendix,argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Erzeugt Kochbuch-PDF aus YAML + LaTeX-Template.")
    ap.add_argument("--title", default=TITLE)
    ap.add_argument("--subtitle", default=SUBTITLE)
    ap.add_argument("--author", default=AUTHOR)
    ap.add_argument("--date", default=DATE_STR, help="Datum (String). Default: heutiges Datum.")
    ap.add_argument("--output", default=str(OUTPUT_PDF), help="Pfad zur Output-PDF.")
    ap.add_argument("--template", default=str(TEMPLATE_TEX), help="Pfad zum template_latex.tex")
    args = ap.parse_args(argv)





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
    raise SystemExit("Should Run With Generate Cookbook or other Scripts")