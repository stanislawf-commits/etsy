"""
listing_agent.py — generuje kompletny listing Etsy dla produktu 3D.

Wejście:  topic (str), product_type (str), size (str)
Wyjście:  dict z polami: slug, title, description, tags, price_suggestion
Zapis:    data/products/{slug}/listing.json  (przez product_io)
"""
import logging
import re

from src.utils.claude_client import claude_json
from src.utils.config_loader import cfg
from src.utils.product_io import save_listing

log = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text)


def _price(product_type: str, size: str) -> float:
    pricing  = cfg("pricing")
    pt_cfg   = pricing["product_types"].get(product_type, {})
    lo       = float(pt_cfg.get("price_min", 8.0))
    hi       = float(pt_cfg.get("price_max", 15.0))
    mid      = (lo + hi) / 2
    mults    = pricing["size_multipliers"]
    mult     = float(mults.get(size.upper(), 1.0))
    raw      = round(mid * mult, 2)
    fmt      = pricing.get("price_format", "dot99")
    base     = int(raw)
    suffix   = 0.99 if fmt == "dot99" else 0.49
    return float(base) + suffix


def _build_prompt(topic: str, product_type: str, size: str) -> str:
    pricing   = cfg("pricing")
    pt_cfg    = pricing["product_types"].get(product_type, {})
    price_lo  = pt_cfg.get("price_min", 8.0)
    price_hi  = pt_cfg.get("price_max", 15.0)

    types_cfg = cfg("product_types")
    size_desc = types_cfg.get("size_descriptions", {}).get(size.upper(), f"approx. 7-8cm")
    material  = types_cfg.get("material", {})
    disclaimer = material.get("disclaimer", "Printed in food-safe PLA. Hand wash only.")
    type_label = types_cfg.get(product_type, {}).get("label", product_type)

    return f"""You are an expert Etsy SEO copywriter specializing in 3D-printed baking and kitchen tools.

Create a complete Etsy listing for the following product:

Product topic:   {topic}
Product type:    {type_label}  ({product_type} = cookie {product_type})
Size:            {size} ({size_desc})
Price range:     {price_lo}–{price_hi} EUR

Return ONLY a valid JSON object with these exact keys:

{{
  "title": "<SEO title, max 140 chars, primary keyword first, include size and material hint>",
  "description": "<min 300 words — structure: intro → features → dimensions → how to use → care → gift ideas → about shop>",
  "tags": ["<tag1>", ..., "<tag13>"],
  "price_suggestion": <number between {price_lo} and {price_hi}>
}}

Tag rules:
- Exactly 13 tags
- Each tag max 20 characters (including spaces)
- Mix: product-specific, occasion, material, style tags

Description rules (CRITICAL):
- Minimum 300 words — count carefully
- Include food-safe disclaimer verbatim: "{disclaimer}"
- Include size hint for {size}: {size_desc}
- Include a 4-5 sentence paragraph about gift-giving occasions
- End with "About our shop" paragraph (3-4 sentences: handmade, small batch, printed to order)
"""


def _validate(data: dict, product_type: str, size: str) -> dict:
    """Sprawdza i naprawia ograniczenia Etsy."""
    etsy = cfg("etsy")
    limits = etsy.get("listing", {})

    # tytuł max 140
    title = str(data.get("title", ""))
    max_t = limits.get("title_max_chars", 140)
    if len(title) > max_t:
        title = title[:max_t - 3] + "..."
    data["title"] = title

    # dokładnie 13 tagów, każdy max 20 znaków
    tag_max = limits.get("tag_max_chars", 20)
    tags = [str(t)[:tag_max] for t in data.get("tags", [])]
    tags = tags[:13]
    while len(tags) < 13:
        tags.append(product_type[:tag_max])
    data["tags"] = tags

    # cena w zakresie
    pricing = cfg("pricing")
    pt_cfg  = pricing["product_types"].get(product_type, {})
    lo      = float(pt_cfg.get("price_min", 8.0))
    hi      = float(pt_cfg.get("price_max", 15.0))
    try:
        price = float(data.get("price_suggestion", _price(product_type, size)))
    except (TypeError, ValueError):
        price = _price(product_type, size)
    data["price_suggestion"] = round(max(lo, min(hi, price)), 2)

    # opis min słów — tylko ostrzeżenie
    min_words = limits.get("description_min_words", 300)
    words = len(str(data.get("description", "")).split())
    if words < min_words:
        log.warning("Description too short: %d words (min %d)", words, min_words)

    return data


# ── Główna funkcja ───────────────────────────────────────────────────────────

def generate(topic: str, product_type: str = "cutter", size: str = "M") -> dict:
    """
    Generuje listing Etsy dla podanego tematu produktu 3D.

    Args:
        topic:        Temat produktu, np. "floral wreath"
        product_type: Typ produktu: "cutter" | "stamp" | "set"
        size:         Rozmiar: "XS" | "S" | "M" | "L" | "XL"

    Returns:
        dict z kluczami: slug, topic, product_type, size,
                         title, description, tags, price_suggestion

    Raises:
        EnvironmentError: brak ANTHROPIC_API_KEY
        ValueError: nieprawidłowy product_type lub size
    """
    pricing = cfg("pricing")
    valid_types = list(pricing["product_types"].keys())
    valid_sizes = list(pricing["size_multipliers"].keys())

    product_type = product_type.lower().strip()
    size         = size.upper().strip()

    if product_type not in valid_types:
        raise ValueError(f"Unknown product_type '{product_type}'. Choose from: {valid_types}")
    if size not in valid_sizes:
        raise ValueError(f"Unknown size '{size}'. Choose from: {valid_sizes}")

    # slug = temat produktu (bez type/size — te info są w meta.json i ścieżce)
    slug   = _slugify(topic)
    prompt = _build_prompt(topic, product_type, size)

    log.info("Generating listing: topic=%r type=%s size=%s slug=%s", topic, product_type, size, slug)

    data = claude_json(prompt, max_tokens=2048)
    data = _validate(data, product_type, size)

    result = {
        "slug":         slug,
        "topic":        topic,
        "product_type": product_type,
        "size":         size,
        **data,
    }

    save_listing(slug, result, product_type=product_type)
    log.info("Listing saved: slug=%s title=%r", slug, result.get("title", "")[:60])
    return result
