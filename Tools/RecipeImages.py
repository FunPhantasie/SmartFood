"""Rezeptbilder: speichern, verkleinern, ausliefern.

Konzept (docs/ProposeLogic.md "Recipe images"):
- pro Rezept zwei Dateien in server_data/images/recipes/: <id>_full.webp (Rezeptseite) und <id>_thumb.webp
  (Karten, Listen). Das Original wird NICHT aufgehoben - nur die verkleinerten Versionen.
- immer 4:3, mittig zugeschnitten -> alle Karten gleich hoch, nichts verzerrt
- WebP mit Qualitaet ~70: etwa 60-120 KB (full) + 15-25 KB (thumb) pro Rezept, 150 Rezepte ~ 15-20 MB
- nie hochskalieren: ein kleines Bild bleibt klein (der Browser skaliert es, statt grosser unscharfer Dateien)
- kein Bild -> Standardbild (Bilder/images.jpg, einmal genauso umgewandelt nach images/default_<size>.webp)

Kommandozeile:
    python Tools/RecipeImages.py import <ordner>    # Dateien <recipe_id>.jpg/.png/.webp... uebernehmen
    python Tools/RecipeImages.py default            # Standardbild neu erzeugen
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / "Server" / "server_data" / "images"
DEFAULT_SOURCE = ROOT / "Bilder" / "images.jpg"

ASPECT = 4 / 3
SIZES = {"full": (1200, 900), "thumb": (480, 360)}   # Breite x Hoehe, hoechstens
QUALITY = {"full": 72, "thumb": 70}
INPUT_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif")


def _crop_to_aspect(im: Image.Image) -> Image.Image:
    """Mittig auf 4:3 zuschneiden (nichts verzerren)."""
    w, h = im.size
    if w / h > ASPECT:                      # zu breit -> links / rechts weg
        new_w = round(h * ASPECT)
        left = (w - new_w) // 2
        return im.crop((left, 0, left + new_w, h))
    new_h = round(w / ASPECT)               # zu hoch -> oben / unten weg
    top = (h - new_h) // 2
    return im.crop((0, top, w, top + new_h))


def render(source: Union[bytes, Path, str]) -> dict[str, bytes]:
    """Bild -> {size: webp-bytes} fuer alle SIZES. Dreht nach EXIF (Handyfotos), schneidet auf 4:3,
    verkleinert nur (nie vergroessern). ValueError, wenn es kein lesbares Bild ist."""
    try:
        im = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
        im.load()
    except Exception as e:
        raise ValueError(f"kein lesbares Bild: {e}") from e
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":                    # PNG mit Transparenz -> weisser Hintergrund
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        im = bg
    im = _crop_to_aspect(im)
    out = {}
    for size, (w, h) in SIZES.items():
        scaled = im.copy()
        if scaled.width > w:
            scaled = scaled.resize((w, h), Image.LANCZOS)
        buf = io.BytesIO()
        scaled.save(buf, "WEBP", quality=QUALITY[size], method=6)
        out[size] = buf.getvalue()
    return out


def _recipe_file(image_dir: Path, recipe_id: int, size: str) -> Path:
    return Path(image_dir) / "recipes" / f"{int(recipe_id)}_{size}.webp"


def save_recipe_image(recipe_id: int, source: Union[bytes, Path, str], image_dir: Path = IMAGE_DIR) -> dict[str, int]:
    """Bild fuer ein Rezept speichern (ersetzt ein altes). Rueckgabe: {size: Dateigroesse in Bytes}."""
    rendered = render(source)
    sizes = {}
    for size, data in rendered.items():
        path = _recipe_file(image_dir, recipe_id, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        sizes[size] = len(data)
    return sizes


def delete_recipe_image(recipe_id: int, image_dir: Path = IMAGE_DIR) -> bool:
    removed = False
    for size in SIZES:
        path = _recipe_file(image_dir, recipe_id, size)
        if path.exists():
            path.unlink()
            removed = True
    return removed


def has_image(recipe_id: int, image_dir: Path = IMAGE_DIR) -> bool:
    return _recipe_file(image_dir, recipe_id, "thumb").exists()


def default_image(size: str, image_dir: Path = IMAGE_DIR, source: Path = DEFAULT_SOURCE) -> Optional[Path]:
    """Standardbild in dieser Groesse (wird beim ersten Mal aus Bilder/images.jpg erzeugt). None, wenn es fehlt."""
    path = Path(image_dir) / f"default_{size}.webp"
    if not path.exists() or (source.exists() and source.stat().st_mtime > path.stat().st_mtime):
        if not source.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        for s, data in render(source).items():
            (Path(image_dir) / f"default_{s}.webp").write_bytes(data)
    return path


def image_file(recipe_id: int, size: str, image_dir: Path = IMAGE_DIR) -> Optional[Path]:
    """Datei fuer /img/recipe/<id>/<size>: eigenes Bild, sonst das Standardbild."""
    if size not in SIZES:
        raise ValueError(f"unknown size {size!r}")
    path = _recipe_file(image_dir, recipe_id, size)
    return path if path.exists() else default_image(size, image_dir)


def import_folder(folder: Path, image_dir: Path = IMAGE_DIR) -> list[str]:
    """Alle Bilder <recipe_id>.<endung> aus folder uebernehmen. Rueckgabe: Protokollzeilen."""
    log = []
    for f in sorted(Path(folder).iterdir()):
        if f.suffix.lower() not in INPUT_SUFFIXES or not f.stem.isdigit():
            continue
        try:
            sizes = save_recipe_image(int(f.stem), f, image_dir)
            log.append(f"{f.name}: {f.stat().st_size // 1024} KB -> "
                       + ", ".join(f"{s} {b // 1024} KB" for s, b in sizes.items()))
        except ValueError as e:
            log.append(f"{f.name}: {e}")
    return log


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "import":
        print("\n".join(import_folder(Path(sys.argv[2]))) or "keine Dateien <recipe_id>.<jpg|png|webp>")
    elif len(sys.argv) == 2 and sys.argv[1] == "default":
        for s in SIZES:
            (IMAGE_DIR / f"default_{s}.webp").unlink(missing_ok=True)
        print(default_image("full"), default_image("thumb"))
    else:
        print(__doc__)
