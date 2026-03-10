"""
restock_alert.py — alert niskiego stanu magazynowego + opcjonalny auto-redruk.

Konfiguracja w config/etsy.yaml (sekcja restock):
    threshold:      3        # alert gdy stock_quantity <= threshold
    action:         log_only # "log_only" | "auto_reprint"
    cooldown_hours: 24       # nie powtarzaj alertu dla tego samego slug

Uruchomienie:
    python cli.py restock-check [--dry]
"""
import logging
from datetime import datetime, timedelta, timezone

from src.utils.config_loader import cfg
from src.db.session import init_db, get_session
from src.db.models import Product, StockEvent
from sqlmodel import select

log = logging.getLogger(__name__)


def run_check(dry_run: bool = False) -> dict:
    """
    Sprawdza stan magazynu i generuje alerty / inicjuje redruki.

    Returns:
        {"alerts": int, "reprints_triggered": int, "checked": int}
    """

    restock_cfg   = cfg("etsy").get("restock", {})
    threshold     = restock_cfg.get("threshold", 3)
    action        = restock_cfg.get("action", "log_only")
    cooldown_h    = restock_cfg.get("cooldown_hours", 24)

    init_db()

    with get_session() as session:
        low_stock = [
            p.model_dump()
            for p in session.exec(
                select(Product).where(
                    Product.status == "listed",
                    Product.stock_quantity <= threshold,
                )
            ).all()
        ]

    if not low_stock:
        log.info("restock_check: no low-stock products found (threshold=%d)", threshold)
        return {"alerts": 0, "reprints_triggered": 0, "checked": 0}

    alerts    = 0
    reprints  = 0

    for prod in low_stock:
        slug  = prod["slug"]
        stock = prod["stock_quantity"]

        if _in_cooldown(slug, cooldown_h):
            log.info("restock_check: %s in cooldown — skipping", slug)
            continue

        log.warning("LOW STOCK: %s — quantity=%d (threshold=%d)", slug, stock, threshold)
        alerts += 1

        if not dry_run:
            _record_event(slug, "restock_alert", stock)

        if action == "auto_reprint" and not dry_run:
            try:
                _trigger_reprint(slug, prod)
                reprints += 1
            except Exception as exc:
                log.error("auto_reprint failed for %s: %s", slug, exc)

    log.info("restock_check: done — alerts=%d reprints=%d", alerts, reprints)
    return {"alerts": alerts, "reprints_triggered": reprints, "checked": len(low_stock)}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _in_cooldown(slug: str, cooldown_hours: int) -> bool:
    """Sprawdza czy dla tego slug był już alert w oknie cooldown."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
        with get_session() as session:
            recent = session.exec(
                select(StockEvent).where(
                    StockEvent.slug == slug,
                    StockEvent.event_type == "restock_alert",
                    StockEvent.created_at >= cutoff,
                )
            ).first()
        return recent is not None
    except Exception:
        return False


def _record_event(slug: str, event_type: str, quantity: int) -> None:
    """Zapisuje StockEvent do DB."""
    try:
        with get_session() as session:
            session.add(StockEvent(
                slug=slug,
                event_type=event_type,
                quantity=quantity,
                source="cron",
            ))
    except Exception as exc:
        log.warning("Could not record %s event for %s: %s", event_type, slug, exc)


def _trigger_reprint(slug: str, prod: dict) -> None:
    """Tworzy nowy draft produktu z tym samym tematem."""
    from src.pipeline.orchestrator import run_pipeline  # lazy — unika circular import

    topic        = prod.get("topic", slug)
    product_type = prod.get("product_type", "cutter")
    size         = prod.get("size", "M")

    log.info("auto_reprint: creating new draft for topic='%s'", topic)
    result = run_pipeline(topic=topic, product_type=product_type, size=size)

    new_slug = result.get("slug", "?")
    _record_event(new_slug, "reprint_triggered", 0)
    log.info("auto_reprint: created %s → %s", topic, new_slug)
