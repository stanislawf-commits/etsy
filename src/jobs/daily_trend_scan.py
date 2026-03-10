"""
daily_trend_scan.py — codzienny skan trendów → auto-tworzenie draftów.

Uruchomienie przez cron (przykład w docs/cron_setup.md):
    0 7 * * * cd /home/dell/etsy3d && .venv/bin/python cli.py trend-scan >> logs/cron.log 2>&1

Lub ręcznie:
    python cli.py trend-scan --max-new 3 --dry
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.agents import trend_agent
from src.pipeline.orchestrator import run_pipeline

log = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parents[2] / "logs"


def run_scan(max_new: int = 3, dry_run: bool = False) -> dict:
    """
    Skanuje trendy i tworzy nowe drafty produktów.

    Args:
        max_new:  Maksymalna liczba nowych produktów na jedno uruchomienie.
        dry_run:  Jeśli True — tylko pokazuje sugestie, nie tworzy produktów.

    Returns:
        {"created": int, "skipped": int, "errors": int, "suggestions": list}
    """

    log.info("daily_trend_scan: start (max_new=%d dry_run=%s)", max_new, dry_run)

    suggestions = trend_agent.suggest()
    log.info("TrendAgent returned %d suggestions", len(suggestions))

    existing_topics = _get_existing_topics()

    created = 0
    skipped = 0
    errors  = 0
    results = []

    for suggestion in suggestions:
        if created >= max_new:
            break

        topic        = suggestion.get("topic", "")
        product_type = suggestion.get("product_type", "cutter")
        size         = suggestion.get("size", "M")

        # Deduplication — pomijaj jeśli temat już istnieje
        if _topic_exists(topic, existing_topics):
            log.info("Skipping duplicate topic: %s", topic)
            skipped += 1
            results.append({"topic": topic, "action": "skipped", "reason": "duplicate"})
            continue

        if dry_run:
            log.info("[DRY RUN] Would create: %s (%s %s)", topic, product_type, size)
            results.append({"topic": topic, "action": "dry_run", "product_type": product_type})
            created += 1
            continue

        try:
            result = run_pipeline(topic=topic, product_type=product_type, size=size)
            slug   = result.get("slug", "?")
            status = result.get("status", "unknown")

            # Zapisz zdarzenie do DB
            _record_auto_draft(slug, topic)

            existing_topics.add(topic.lower())
            created += 1
            results.append({"topic": topic, "slug": slug, "status": status, "action": "created"})
            log.info("Created: %s → %s (%s)", topic, slug, status)

        except Exception as exc:
            errors += 1
            results.append({"topic": topic, "action": "error", "error": str(exc)})
            log.warning("Failed to create product for topic '%s': %s", topic, exc)

    summary = {"created": created, "skipped": skipped, "errors": errors, "suggestions": results}
    _write_log(summary, dry_run)
    log.info("daily_trend_scan: done — created=%d skipped=%d errors=%d", created, skipped, errors)
    return summary


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_existing_topics() -> set[str]:
    """Zbiera tematy istniejących produktów (z meta.json + DB)."""
    from src.utils.product_io import DATA_DIR
    import json as _json

    topics: set[str] = set()

    # Z plików meta.json
    for meta_file in DATA_DIR.glob("*/meta.json"):
        try:
            data = _json.loads(meta_file.read_text())
            topic = data.get("topic", "")
            if topic:
                topics.add(topic.lower())
        except Exception:
            pass

    # Z DB (jeśli dostępna)
    try:
        from src.db.session import get_session
        from src.db.models import Product
        from sqlmodel import select
        with get_session() as session:
            for p in session.exec(select(Product)).all():
                if p.topic:
                    topics.add(p.topic.lower())
    except Exception:
        pass

    return topics


def _topic_exists(topic: str, existing: set[str]) -> bool:
    """Sprawdza czy temat (lub bardzo podobny) już istnieje."""
    normalized = topic.lower().strip()
    return normalized in existing


def _record_auto_draft(slug: str, topic: str) -> None:
    """Zapisuje StockEvent z typem auto_draft_created."""
    try:
        from src.db.session import get_session
        from src.db.models import StockEvent
        with get_session() as session:
            session.add(StockEvent(
                slug=slug,
                event_type="auto_draft_created",
                quantity=0,
                source="cron",
                payload=json.dumps({"topic": topic}),
            ))
    except Exception as exc:
        log.warning("Could not record auto_draft event for %s: %s", slug, exc)


def _write_log(summary: dict, dry_run: bool) -> None:
    """Zapisuje podsumowanie do logs/daily_scan_{date}.json."""
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        suffix   = "_dry" if dry_run else ""
        log_path = LOGS_DIR / f"daily_scan_{date_str}{suffix}.json"
        log_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        log.info("Scan log written: %s", log_path)
    except Exception as exc:
        log.warning("Could not write scan log: %s", exc)
