"""
trend_agent.py — analizuje trendy i sugeruje tematy produktów.

Strategia (kolejność prób):
  1. pytrends  — Google Trends (wymaga pytrends w env)
  2. static    — baza z config/trends.yaml (zawsze dostępna)

Wynik zapisywany do logs/trend_suggestions.json.
"""
import json
import logging
import random
from datetime import datetime
from pathlib import Path

from src.utils.config_loader import cfg

log = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parents[2] / "logs"


# ── Google Trends (pytrends) ─────────────────────────────────────────────────

def _suggest_pytrends(category: str, count: int, geo: str, hl: str, context: str) -> list[dict] | None:
    """
    Pobiera sugestie tematów z Google Trends przez pytrends.

    Returns:
        Lista dictów z topic/product_type/season/priority/reason
        lub None gdy pytrends niedostępny lub wystąpił błąd.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.debug("pytrends not installed — skipping Google Trends")
        return None

    try:
        pytrends = TrendReq(hl=hl, tz=360, timeout=(10, 25))

        # Pobierz trending searches w kategorii baking
        # Używamy related queries dla kontekstu "cookie cutter"
        pytrends.build_payload([context], cat=0, timeframe="today 3-m", geo=geo, gprop="")
        related = pytrends.related_queries()

        rising = related.get(context, {}).get("rising")
        if rising is None or rising.empty:
            log.info("pytrends: no rising queries found for %r", context)
            return None

        # Weź top rising queries jako tematy
        top_rising = rising.head(count * 2)["query"].tolist()
        log.info("pytrends: found %d rising queries", len(top_rising))

        # Połącz z bazą statyczną — wzbogać o product_type i reason
        static_topics = _load_static_topics()
        static_map    = {t["topic"].lower(): t for t in static_topics}

        suggestions = []
        for query in top_rising:
            q_lower = query.lower()
            # Sprawdź czy jest w naszej bazie
            matched = static_map.get(q_lower)
            if matched:
                suggestions.append(matched)
            else:
                # Nowy trend — dedukuj product_type
                product_type = _infer_product_type(query)
                suggestions.append({
                    "topic":        query,
                    "product_type": product_type,
                    "season":       "trend",
                    "priority":     "medium",
                    "reason":       f"Rising Google Trends query: '{query}' (3-month window, {geo})",
                    "source":       "pytrends",
                })

            if len(suggestions) >= count:
                break

        return suggestions if suggestions else None

    except Exception as exc:
        log.warning("pytrends error: %s — falling back to static", exc)
        return None


def _infer_product_type(topic: str) -> str:
    """Dedukuje typ produktu z tematu (prosta heurystyka)."""
    topic_lower = topic.lower()
    stamp_hints  = ["stamp", "emboss", "press", "imprint", "pattern", "leaf", "botanical"]
    set_hints    = ["set", "collection", "bundle", "kit", "combo"]
    for hint in set_hints:
        if hint in topic_lower:
            return "set"
    for hint in stamp_hints:
        if hint in topic_lower:
            return "stamp"
    return "cutter"


# ── Baza statyczna ───────────────────────────────────────────────────────────

def _load_static_topics() -> list[dict]:
    """Ładuje wszystkie tematy ze statycznej bazy (config/trends.yaml)."""
    trends_cfg = cfg("trends")
    topics_cfg = trends_cfg.get("topics", {})

    all_topics: list[dict] = []

    # Evergreen
    for t in topics_cfg.get("evergreen", []):
        t.setdefault("season", "evergreen")
        t.setdefault("source", "static")
        all_topics.append(t)

    # Holiday — bieżący kwartał i sąsiednie
    month = datetime.now().month
    current_q = f"Q{(month - 1) // 3 + 1}"
    holiday_cfg = topics_cfg.get("holiday", {})

    for q_key, q_topics in holiday_cfg.items():
        for t in q_topics:
            t.setdefault("season", "holiday")
            t.setdefault("source", "static")
            # Bieżący kwartał → wyższy priorytet
            if q_key == current_q:
                t = dict(t)  # kopia by nie mutować oryginału
                t["priority"] = "high" if t.get("priority") == "medium" else t.get("priority", "high")
                t["reason"]   = f"[Seasonal Q{current_q[-1]}] " + t.get("reason", "")
            all_topics.append(t)

    return all_topics


def _suggest_static(count: int) -> list[dict]:
    """
    Wybiera sugestie z bazy statycznej.
    Priorytetuje 'high', reszta losowo.
    """
    all_topics = _load_static_topics()

    high = [t for t in all_topics if t.get("priority") == "high"]
    rest = [t for t in all_topics if t.get("priority") != "high"]

    random.shuffle(high)
    random.shuffle(rest)

    return (high + rest)[:count]


# ── Główna funkcja ───────────────────────────────────────────────────────────

def suggest(category: str = "baking") -> list[dict]:
    """
    Zwraca listę sugestii tematów produktów.

    Strategia:
      1. Spróbuj pytrends (Google Trends)
      2. Fallback: statyczna baza z config/trends.yaml

    Args:
        category: Kategoria produktów (obecnie "baking")

    Returns:
        Lista dictów: topic, product_type, season, priority, reason, source
    """
    log.info("trend_agent.suggest called, category=%r", category)

    trends_cfg = cfg("trends")
    strategy   = trends_cfg.get("strategy", {})
    count      = strategy.get("suggestions_count", 5)
    methods    = strategy.get("methods", ["static"])
    geo        = strategy.get("pytrends_geo", "US")
    hl         = strategy.get("pytrends_hl", "en-US")
    context    = strategy.get("pytrends_context", "cookie cutter")

    picks: list[dict] | None = None

    for method in methods:
        if method == "pytrends":
            picks = _suggest_pytrends(category, count, geo, hl, context)
            if picks:
                log.info("Using pytrends: %d suggestions", len(picks))
                break
        elif method == "static":
            picks = _suggest_static(count)
            log.info("Using static db: %d suggestions", len(picks))
            break

    if not picks:
        picks = _suggest_static(count)

    # Zapis do logs/trend_suggestions.json
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = LOGS_DIR / "trend_suggestions.json"
    payload  = {
        "generated_at": datetime.now().isoformat(),
        "category":     category,
        "method":       picks[0].get("source", "static") if picks else "static",
        "suggestions":  picks,
    }
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info("Saved trend suggestions to %s", out_file)

    return picks
