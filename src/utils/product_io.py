"""
product_io.py — centralny I/O dla danych produktu.

Struktura katalogów (v3):
    data/products/{product_type}/{slug}/
        meta.json
        listing.json
        source/   S.svg  M.svg  L.svg
        models/   S.stl  M.stl  L.stl
        renders/  hero.jpg  lifestyle.jpg  sizes.jpg  detail.jpg  info.jpg

Użycie:
    from src.utils.product_io import load_meta, save_meta, update_meta
    from src.utils.product_io import load_listing, save_listing
    from src.utils.product_io import product_dir, ensure_product_dir
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parents[2] / "data" / "products"

# Znane typy produktów — podkatalogi w DATA_DIR
PRODUCT_TYPES = ("cutter", "stamp", "set")


# ── Ścieżki ─────────────────────────────────────────────────────────────────

def product_dir(slug: str, product_type: str = "cutter") -> Path:
    """
    Zwraca ścieżkę do katalogu produktu: data/products/{type}/{slug}/.
    Nie tworzy katalogu.
    """
    return DATA_DIR / product_type / slug


def find_product_dir(slug: str) -> Path | None:
    """
    Szuka folderu produktu po slug we wszystkich typach.
    Używane gdy typ nie jest znany (np. CLI status <slug>).
    Akceptuje folder z meta.json LUB listing.json.

    Returns:
        Path do folderu lub None jeśli nie znaleziono.
    """
    for ptype in PRODUCT_TYPES:
        candidate = DATA_DIR / ptype / slug
        if candidate.is_dir() and (
            (candidate / "meta.json").exists() or
            (candidate / "listing.json").exists()
        ):
            return candidate
    return None


def ensure_product_dir(slug: str, product_type: str = "cutter") -> Path:
    """Tworzy katalog produktu jeśli nie istnieje. Zwraca Path."""
    d = product_dir(slug, product_type)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── meta.json ────────────────────────────────────────────────────────────────

def load_meta(slug: str, product_type: str = "") -> dict:
    """
    Ładuje meta.json dla produktu.
    Jeśli product_type nie podany — szuka we wszystkich typach.

    Returns:
        dict z metadanymi lub pusty dict gdy plik nie istnieje.
    """
    if product_type:
        path = product_dir(slug, product_type) / "meta.json"
    else:
        d = find_product_dir(slug)
        path = (d / "meta.json") if d else (DATA_DIR / slug / "meta.json")

    if not path.exists():
        log.debug("meta.json not found for slug=%r", slug)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("Corrupt meta.json for slug=%r: %s", slug, e)
        return {}


def save_meta(slug: str, meta: dict, product_type: str = "") -> Path:
    """
    Zapisuje meta.json. Zawsze ustawia updated_at.

    Returns:
        Path do zapisanego pliku.
    """
    ptype = product_type or meta.get("product_type", "cutter")
    d     = ensure_product_dir(slug, ptype)
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = d / "meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.debug("Saved meta.json: slug=%r status=%r", slug, meta.get("status"))
    return path


def update_meta(slug: str, **fields) -> dict:
    """
    Ładuje meta.json, aktualizuje podane pola i zapisuje.

    Przykład:
        update_meta("floral-wreath", status="listed", etsy_listing_id=123)

    Returns:
        Zaktualizowany dict meta.
    """
    meta = load_meta(slug)
    meta.update(fields)
    save_meta(slug, meta)
    return meta


def mark_step_done(slug: str, step: str) -> dict:
    """
    Dodaje krok do steps_completed w meta.json (idempotentne).

    Returns:
        Zaktualizowany dict meta.
    """
    meta  = load_meta(slug)
    steps = meta.get("steps_completed", [])
    if step not in steps:
        steps.append(step)
        meta["steps_completed"] = steps
        save_meta(slug, meta)
        log.debug("Step marked done: slug=%r step=%r", slug, step)
    return meta


def is_step_done(slug: str, step: str) -> bool:
    """Sprawdza czy krok jest oznaczony jako ukończony."""
    meta = load_meta(slug)
    return step in meta.get("steps_completed", [])


# ── listing.json ─────────────────────────────────────────────────────────────

def load_listing(slug: str, product_type: str = "") -> dict:
    """
    Ładuje listing.json dla produktu.

    Returns:
        dict z danymi listingu lub pusty dict gdy plik nie istnieje.
    """
    if product_type:
        path = product_dir(slug, product_type) / "listing.json"
    else:
        d = find_product_dir(slug)
        path = (d / "listing.json") if d else (DATA_DIR / slug / "listing.json")

    if not path.exists():
        log.debug("listing.json not found for slug=%r", slug)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("Corrupt listing.json for slug=%r: %s", slug, e)
        return {}


def save_listing(slug: str, listing: dict, product_type: str = "") -> Path:
    """
    Zapisuje listing.json.

    Returns:
        Path do zapisanego pliku.
    """
    ptype = product_type or listing.get("product_type", "cutter")
    d     = ensure_product_dir(slug, ptype)
    path  = d / "listing.json"
    path.write_text(json.dumps(listing, indent=2, ensure_ascii=False), encoding="utf-8")
    log.debug("Saved listing.json: slug=%r title=%r", slug, listing.get("title", "")[:40])
    return path


# ── Listowanie produktów ─────────────────────────────────────────────────────

def list_all_slugs() -> list[str]:
    """
    Zwraca listę slugów wszystkich produktów posortowaną: najpierw wg typu, potem slug.
    Szuka w DATA_DIR/{type}/{slug}/meta.json.
    """
    if not DATA_DIR.exists():
        return []
    slugs = []
    for ptype in PRODUCT_TYPES:
        type_dir = DATA_DIR / ptype
        if not type_dir.is_dir():
            continue
        for d in sorted(type_dir.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                slugs.append(d.name)
    return slugs


def list_by_status(status: str) -> list[str]:
    """Zwraca slugi produktów o danym statusie."""
    result = []
    for slug in list_all_slugs():
        meta = load_meta(slug)
        if meta.get("status") == status:
            result.append(slug)
    return result


def load_all_products() -> list[dict]:
    """
    Ładuje meta + listing dla wszystkich produktów.

    Returns:
        Lista dictów: {slug, product_type, meta, listing}
    """
    products = []
    for ptype in PRODUCT_TYPES:
        type_dir = DATA_DIR / ptype
        if not type_dir.is_dir():
            continue
        for d in sorted(type_dir.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                slug = d.name
                products.append({
                    "slug":         slug,
                    "product_type": ptype,
                    "meta":         load_meta(slug, ptype),
                    "listing":      load_listing(slug, ptype),
                })
    return products
