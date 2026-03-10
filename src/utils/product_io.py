"""
product_io.py — centralny I/O dla danych produktu.

Wszystkie operacje na meta.json i listing.json przechodzą przez ten moduł.
Żaden agent nie powinien samodzielnie robić json.loads/json.dumps na tych plikach.

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


# ── Ścieżki ─────────────────────────────────────────────────────────────────

def product_dir(slug: str) -> Path:
    """Zwraca ścieżkę do katalogu produktu. Nie tworzy go."""
    return DATA_DIR / slug


def ensure_product_dir(slug: str) -> Path:
    """Tworzy katalog produktu jeśli nie istnieje. Zwraca Path."""
    d = product_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── meta.json ────────────────────────────────────────────────────────────────

def load_meta(slug: str) -> dict:
    """
    Ładuje meta.json dla produktu.

    Returns:
        dict z metadanymi lub pusty dict gdy plik nie istnieje.
    """
    path = product_dir(slug) / "meta.json"
    if not path.exists():
        log.debug("meta.json not found for slug=%r", slug)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("Corrupt meta.json for slug=%r: %s", slug, e)
        return {}


def save_meta(slug: str, meta: dict) -> Path:
    """
    Zapisuje meta.json. Zawsze ustawia updated_at.

    Returns:
        Path do zapisanego pliku.
    """
    d = ensure_product_dir(slug)
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = d / "meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.debug("Saved meta.json: slug=%r status=%r", slug, meta.get("status"))
    return path


def update_meta(slug: str, **fields) -> dict:
    """
    Ładuje meta.json, aktualizuje podane pola i zapisuje.

    Przykład:
        update_meta("floral-cutter-m", status="listed", etsy_listing_id=123)

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
    meta = load_meta(slug)
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

def load_listing(slug: str) -> dict:
    """
    Ładuje listing.json dla produktu.

    Returns:
        dict z danymi listingu lub pusty dict gdy plik nie istnieje.
    """
    path = product_dir(slug) / "listing.json"
    if not path.exists():
        log.debug("listing.json not found for slug=%r", slug)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error("Corrupt listing.json for slug=%r: %s", slug, e)
        return {}


def save_listing(slug: str, listing: dict) -> Path:
    """
    Zapisuje listing.json.

    Returns:
        Path do zapisanego pliku.
    """
    d = ensure_product_dir(slug)
    path = d / "listing.json"
    path.write_text(json.dumps(listing, indent=2, ensure_ascii=False), encoding="utf-8")
    log.debug("Saved listing.json: slug=%r title=%r", slug, listing.get("title", "")[:40])
    return path


# ── Listowanie produktów ─────────────────────────────────────────────────────

def list_all_slugs() -> list[str]:
    """Zwraca listę slugów wszystkich produktów posortowaną alfabetycznie."""
    if not DATA_DIR.exists():
        return []
    return sorted(
        d.name for d in DATA_DIR.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )


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
        Lista dictów: {slug, meta, listing}
    """
    products = []
    for slug in list_all_slugs():
        products.append({
            "slug":    slug,
            "meta":    load_meta(slug),
            "listing": load_listing(slug),
        })
    return products
