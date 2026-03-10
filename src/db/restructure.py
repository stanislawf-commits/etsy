"""
restructure.py — migracja struktury data/products/ do formatu v3.

Zmiany:
  - Usuwa niekompletne foldery (bez meta.json)
  - Usuwa *_dalle_raw.png, listing_export.json, design.json
  - Przenosi produkty do data/products/{type}/{topic_slug}/
  - Skraca nazwy plików: S.svg, M.svg, L.svg / S.stl, M.stl, L.stl

Uruchomienie:
    python src/db/restructure.py [--dry]
"""
import json
import re
import shutil
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parents[2] / "data" / "products"


def _topic_slug(slug: str, product_type: str) -> str:
    """
    Wyciąga temat z obecnego sluga (usuwa -{type}-{size} suffix).
    np. 'floral-wreath-cutter-m' + type='cutter' → 'floral-wreath'
    """
    # Usuń rozmiar na końcu (-s/-m/-l/-xs/-xl)
    result = re.sub(r"-(?:xs|s|m|l|xl)$", "", slug, flags=re.IGNORECASE)
    # Usuń typ na końcu
    result = re.sub(rf"-{re.escape(product_type)}$", "", result, flags=re.IGNORECASE)
    return result or slug


def _short_size(filename: str) -> str | None:
    """
    'floral-wreath-cutter-m-L.svg' → 'L'
    'floral-wreath-cutter-m-L_L_cutter.stl' → 'L'

    Patrzy na OSTATNI segment po '-' przed rozszerzeniem (SVG)
    lub przed pierwszym '_' po ostatnim '-' (STL).
    """
    stem = Path(filename).stem  # bez rozszerzenia

    # SVG: ostatni segment po '-' to rozmiar
    parts = stem.split("-")
    last  = parts[-1].upper()
    if last in ("S", "M", "L", "XS", "XL"):
        return last

    # STL: wzorzec -{size}_{size}_{type}
    m = re.search(r"-([SMLsml])_[SMLsml]_\w+$", stem)
    if m:
        return m.group(1).upper()

    return None


def restructure(dry_run: bool = False) -> dict:
    stats = {"removed_dirs": 0, "removed_files": 0, "moved": 0, "errors": 0}
    log = []

    # ── 1. Usuń niekompletne foldery (bez meta.json) ─────────────────────────
    for d in sorted(DATA_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if not (d / "meta.json").exists():
            log.append(f"  [DEL DIR]  {d.name}  (no meta.json)")
            if not dry_run:
                shutil.rmtree(d)
            stats["removed_dirs"] += 1

    # ── 2. Przenieś kompletne produkty do {type}/{topic}/ ────────────────────
    # Ponownie skanuj (po usunięciu)
    to_move = []
    for d in sorted(DATA_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        meta_path = d / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        product_type = meta.get("product_type", "cutter")
        old_slug     = meta.get("slug", d.name)
        new_slug     = _topic_slug(old_slug, product_type)
        dest         = DATA_DIR / product_type / new_slug
        to_move.append((d, dest, meta, old_slug, new_slug, product_type))

    for src, dest, meta, old_slug, new_slug, product_type in to_move:
        if src == dest:
            log.append(f"  [SKIP]     {src.name}  (already correct)")
            continue

        log.append(f"  [MOVE]     {src.name} → {product_type}/{new_slug}")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, dirs_exist_ok=False)
            # Zaktualizuj slug w meta.json
            meta["slug"] = new_slug
            (dest / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            shutil.rmtree(src)
        stats["moved"] += 1

    # ── 3. Porządkuj pliki wewnątrz każdego produktu ─────────────────────────
    for type_dir in sorted(DATA_DIR.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        for prod_dir in sorted(type_dir.iterdir()):
            if not prod_dir.is_dir():
                continue
            _clean_product_dir(prod_dir, dry_run, log, stats)

    # Wypisz raport
    for line in log:
        print(line)
    print()
    print(f"  Usunięto folderów:  {stats['removed_dirs']}")
    print(f"  Przeniesionych:     {stats['moved']}")
    print(f"  Usuniętych plików:  {stats['removed_files']}")
    print(f"  Błędów:             {stats['errors']}")
    return stats


def _clean_product_dir(prod_dir: Path, dry_run: bool, log: list, stats: dict) -> None:
    """Czyści i skraca nazwy plików wewnątrz folderu produktu."""

    # Usuń design.json (redundantne)
    for junk in ["design.json", "listing_export.json"]:
        f = prod_dir / junk
        if f.exists():
            log.append(f"    [DEL FILE] {prod_dir.parent.name}/{prod_dir.name}/{junk}")
            if not dry_run:
                f.unlink()
            stats["removed_files"] += 1

    # Usuń *_dalle_raw.png z source/
    source_dir = prod_dir / "source"
    if source_dir.exists():
        for png in source_dir.glob("*_dalle_raw.png"):
            log.append(f"    [DEL FILE] .../source/{png.name}")
            if not dry_run:
                png.unlink()
            stats["removed_files"] += 1

    # Skróć nazwy SVG: {slug}-L.svg → L.svg
    if source_dir.exists():
        for svg in sorted(source_dir.glob("*.svg")):
            size = _short_size(svg.name)
            if size and svg.name != f"{size}.svg":
                new_name = source_dir / f"{size}.svg"
                log.append(f"    [RENAME]   source/{svg.name} → {size}.svg")
                if not dry_run:
                    svg.rename(new_name)

    # Skróć nazwy STL: {slug}-L_L_cutter.stl → L.stl
    models_dir = prod_dir / "models"
    if models_dir.exists():
        for stl in sorted(models_dir.glob("*.stl")):
            size = _short_size(stl.name)
            if size and stl.name != f"{size}.stl":
                new_name = models_dir / f"{size}.stl"
                log.append(f"    [RENAME]   models/{stl.name} → {size}.stl")
                if not dry_run:
                    stl.rename(new_name)


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if dry:
        print("=== DRY RUN — żadne zmiany nie zostaną zapisane ===\n")
    else:
        print("=== RESTRUCTURE — zmiany zostaną zapisane ===\n")
    restructure(dry_run=dry)
