"""
migrate.py — jednorazowa migracja produktów z flat JSON do SQLite.

Uruchomienie:
    python -m src.db.migrate          # migruje wszystkie produkty
    python -m src.db.migrate --dry    # podgląd bez zapisu

Idempotentne: produkty z istniejącym slug są aktualizowane, nie duplikowane.
"""
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parents[2] / "data" / "products"


def migrate(dry_run: bool = False) -> dict:
    """
    Migruje wszystkie produkty z JSON do SQLite.

    Returns:
        {"migrated": int, "skipped": int, "errors": int}
    """
    from src.db.session import init_db, get_session
    from src.db.models import Product

    if not dry_run:
        init_db()

    stats = {"migrated": 0, "skipped": 0, "errors": 0}

    # Nowa struktura v3: DATA_DIR/{product_type}/{slug}/meta.json (2 poziomy głębiej)
    product_dirs = sorted(
        d
        for type_dir in DATA_DIR.iterdir() if type_dir.is_dir()
        for d in type_dir.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )

    log.info("Found %d product dirs to migrate", len(product_dirs))

    for product_dir in product_dirs:
        slug = product_dir.name
        try:
            meta    = json.loads((product_dir / "meta.json").read_text())
            listing = {}
            listing_path = product_dir / "listing.json"
            if listing_path.exists():
                listing = json.loads(listing_path.read_text())

            # Zlicz pliki
            svg_count    = len(list((product_dir / "source").glob("*.svg")))   if (product_dir / "source").exists()  else 0
            stl_count    = len(list((product_dir / "models").glob("*.stl")))   if (product_dir / "models").exists()  else 0
            render_count = len(list((product_dir / "renders").glob("*.jpg")))  if (product_dir / "renders").exists() else 0

            tags = listing.get("tags", [])

            product = Product(
                slug         = slug,
                topic        = meta.get("topic", slug),
                product_type = meta.get("product_type", "cutter"),
                size         = meta.get("size", "M"),
                status       = meta.get("status", "draft"),
                title        = listing.get("title"),
                price        = listing.get("price_suggestion"),
                tags_json    = json.dumps(tags),
                etsy_listing_id = meta.get("etsy", {}).get("listing_id") if isinstance(meta.get("etsy"), dict) else None,
                etsy_url        = meta.get("etsy", {}).get("url")         if isinstance(meta.get("etsy"), dict) else None,
                steps_json   = json.dumps(meta.get("steps_completed", [])),
                svg_count    = svg_count,
                stl_count    = stl_count,
                render_count = render_count,
                render_engine = meta.get("render_engine"),
                created_at   = _parse_dt(meta.get("created_at")),
                updated_at   = _parse_dt(meta.get("updated_at") or meta.get("created_at")),
            )

            if dry_run:
                log.info("[DRY] Would migrate: %s (status=%s)", slug, product.status)
                stats["migrated"] += 1
                continue

            with get_session() as session:
                existing = session.get(Product, slug)
                if existing:
                    # Aktualizuj istniejący
                    for field in ["topic", "product_type", "size", "status",
                                  "title", "price", "tags_json", "etsy_listing_id",
                                  "etsy_url", "steps_json", "svg_count", "stl_count",
                                  "render_count", "render_engine", "updated_at"]:
                        setattr(existing, field, getattr(product, field))
                    session.add(existing)
                else:
                    session.add(product)

            stats["migrated"] += 1
            log.debug("Migrated: %s", slug)

        except Exception as exc:
            log.error("Error migrating %s: %s", slug, exc)
            stats["errors"] += 1

    return stats


def _parse_dt(value):
    """Parsuje ISO datetime string lub zwraca teraz."""
    from datetime import datetime, timezone
    if not value:
        return datetime.now(timezone.utc)
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.now(timezone.utc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dry = "--dry" in sys.argv
    if dry:
        print("DRY RUN — no changes written\n")
    stats = migrate(dry_run=dry)
    print(f"\nMigration complete:")
    print(f"  Migrated: {stats['migrated']}")
    print(f"  Errors:   {stats['errors']}")
