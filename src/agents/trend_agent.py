"""
trend_agent.py - analizuje trendy i sugeruje tematy produktów.

Baza tematów evergreen zakodowana na stałe (bez zewnętrznych API).
Wynik zapisywany do logs/trend_suggestions.json.
"""
import json
import logging
import random
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parents[2] / "logs"

# ── baza tematów evergreen ───────────────────────────────────────────────────

EVERGREEN_TOPICS: list[dict] = [
    {
        "topic": "floral wreath",
        "product_type": "cutter",
        "season": "evergreen",
        "priority": "high",
        "reason": "Floral designs are consistently top sellers on Etsy year-round; wreaths appeal to home bakers and gifters alike.",
    },
    {
        "topic": "botanical leaf",
        "product_type": "stamp",
        "season": "evergreen",
        "priority": "high",
        "reason": "Botanical motifs have strong search volume in the baking niche and pair well with cottagecore aesthetics.",
    },
    {
        "topic": "celestial moon and stars",
        "product_type": "set",
        "season": "evergreen",
        "priority": "high",
        "reason": "Celestial themes are among the fastest-growing niches; moon + stars sets drive higher average order value.",
    },
    {
        "topic": "geometric hexagon",
        "product_type": "cutter",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Geometric shapes appeal to minimalist bakers and are popular for custom cakes and modern cookie boards.",
    },
    {
        "topic": "cottagecore mushroom",
        "product_type": "cutter",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Cottagecore is a sustained social-media trend driving strong Etsy search traffic for whimsical baking tools.",
    },
    {
        "topic": "butterfly",
        "product_type": "stamp",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Butterflies are perennial favourites for spring gifting and children's parties, ensuring steady demand.",
    },
    {
        "topic": "heart",
        "product_type": "cutter",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Hearts are the most-searched cookie cutter shape and convert especially well around Valentine's Day and anniversaries.",
    },
    {
        "topic": "boho sun",
        "product_type": "stamp",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Boho / retro sun motifs are trending in home décor and translate naturally to cookie stamps and clay tools.",
    },
    {
        "topic": "monogram letter",
        "product_type": "cutter",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Personalised monogram cutters appeal to custom-order bakers and bridal markets, supporting premium pricing.",
    },
    {
        "topic": "kitchen classics rolling pin",
        "product_type": "stamp",
        "season": "evergreen",
        "priority": "medium",
        "reason": "Classic kitchen motifs resonate with gift-buyers looking for novelty baking gifts for home cooks.",
    },
]

# ── tematy świąteczne Q4 ─────────────────────────────────────────────────────

HOLIDAY_TOPICS: list[dict] = [
    {
        "topic": "christmas snowflake",
        "product_type": "cutter",
        "season": "holiday",
        "priority": "high",
        "reason": "Snowflake cutters peak in November–December and are one of the highest-volume holiday searches on Etsy.",
    },
    {
        "topic": "christmas tree",
        "product_type": "set",
        "season": "holiday",
        "priority": "high",
        "reason": "Christmas tree sets (cutter + stamp) command premium prices in Q4 and generate strong repeat buyers.",
    },
    {
        "topic": "gingerbread house",
        "product_type": "cutter",
        "season": "holiday",
        "priority": "high",
        "reason": "Gingerbread house cutters see a major search spike from October through December every year.",
    },
]


# ── główna funkcja ───────────────────────────────────────────────────────────

def suggest(category: str = "baking") -> list[dict]:
    """
    Zwraca listę 5 propozycji tematów produktów.

    Args:
        category: Kategoria produktów (obecnie obsługiwana: "baking").

    Returns:
        Lista 5 dictów z kluczami: topic, product_type, season, priority, reason.
    """
    log.info("trend_agent.suggest called, category=%r", category)

    pool = list(EVERGREEN_TOPICS)

    # Q4 (oct–dec) → dodaj tematy świąteczne i wylosuj z poszerzonej puli
    month = datetime.now().month
    if month in (10, 11, 12):
        log.info("Q4 detected – adding holiday topics to pool")
        pool = HOLIDAY_TOPICS + pool  # holiday na przodzie, by miały szansę trafić do top 5

    # priorytet "high" zawsze uwzględniony (floral / celestial / botanical)
    high = [t for t in pool if t["priority"] == "high"]
    rest = [t for t in pool if t["priority"] != "high"]

    random.shuffle(high)
    random.shuffle(rest)

    # weź tyle "high" ile jest (max 5), dopełnij resztą
    picks = (high + rest)[:5]

    log.info("Selected %d topics", len(picks))

    # zapis do logs/trend_suggestions.json
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = LOGS_DIR / "trend_suggestions.json"
    payload = {
        "generated_at": datetime.now().isoformat(),
        "category": category,
        "suggestions": picks,
    }
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info("Saved trend suggestions to %s", out_file)

    return picks
