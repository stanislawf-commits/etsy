"""
listing_agent.py - generuje kompletny listing Etsy dla produktu 3D.

Wejście:  topic (str), product_type (str), size (str)
Wyjście:  dict z polami: title, description, tags, price
Zapis:    data/products/{slug}/listing.json
"""
import json
import logging
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── ceny bazowe EUR (min, max) ──────────────────────────────────────────────
PRICE_RANGES: dict[str, tuple[float, float]] = {
    "cutter": (8.0, 15.0),
    "stamp":  (10.0, 18.0),
    "set":    (15.0, 25.0),
}

# ── mnożnik rozmiaru ────────────────────────────────────────────────────────
SIZE_MULTIPLIER: dict[str, float] = {
    "XS": 0.85,
    "S":  0.90,
    "M":  1.00,
    "L":  1.15,
    "XL": 1.30,
}

DATA_DIR = Path(__file__).parents[2] / "data" / "products"
MODEL = "claude-sonnet-4-20250514"


# ── helper ──────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text)


def _price(product_type: str, size: str) -> float:
    lo, hi = PRICE_RANGES.get(product_type, (8.0, 15.0))
    mid = (lo + hi) / 2
    multiplier = SIZE_MULTIPLIER.get(size.upper(), 1.0)
    raw = round(mid * multiplier, 2)
    # zaokrąglij do .49 lub .99
    base = int(raw)
    return float(base) + 0.99


def _build_prompt(topic: str, product_type: str, size: str) -> str:
    price_lo, price_hi = PRICE_RANGES.get(product_type, (8.0, 15.0))
    return f"""You are an expert Etsy SEO copywriter specializing in 3D-printed baking and kitchen tools.

Create a complete Etsy listing for the following product:

Product topic:   {topic}
Product type:    {product_type}  (cutter = cookie cutter, stamp = cookie stamp, set = cutter+stamp set)
Size:            {size}
Price range:     {price_lo}–{price_hi} EUR

Return ONLY a valid JSON object with these exact keys (no markdown, no explanation):

{{
  "title": "<SEO title, max 140 chars, primary keyword first, include size and material hint>",
  "description": "<min 300 words; include: what the product is, 3D-printed food-safe PLA note, approximate dimensions for size {size}, how to use, cleaning instructions (hand wash only, no dishwasher), gift idea angle, shop note>",
  "tags": ["<tag1>", "<tag2>", "...", "<tag13>"],
  "price_suggestion": <number between {price_lo} and {price_hi}>
}}

Tag rules:
- Exactly 13 tags
- Each tag max 20 characters (including spaces)
- Use popular Etsy search phrases relevant to the product
- Mix: product-specific, occasion, material, style tags

Description rules (CRITICAL — count every word before returning):
- Write in fluent English
- MINIMUM 300 words — count carefully; if under 300, expand before returning
- Structure: intro (what it is) → features → dimensions → how to use → care instructions → gift ideas → about shop
- Include food-safe disclaimer verbatim: "Printed in food-safe PLA. Hand wash only – not dishwasher safe. Do not use in microwave or oven."
- Include size hint for "{size}": XS≈5cm, S≈6cm, M≈7-8cm, L≈9-10cm, XL≈11cm+
- Include a full paragraph (4-5 sentences) about gift-giving occasions
- End with a "About our shop" paragraph (3-4 sentences about handmade, small batch, printed to order, US/EU shipping)
"""


def _parse_response(raw: str) -> dict:
    """Wyciąga JSON z odpowiedzi modelu (obsługuje markdown fences)."""
    # usuń ewentualne ```json ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    return json.loads(cleaned)


def _validate(data: dict, topic: str, product_type: str, size: str) -> dict:
    """Sprawdza i naprawia ograniczenia Etsy."""
    # tytuł max 140
    title = str(data.get("title", topic))
    if len(title) > 140:
        title = title[:137] + "..."
    data["title"] = title

    # dokładnie 13 tagów, każdy max 20 znaków
    tags = [str(t)[:20] for t in data.get("tags", [])]
    tags = tags[:13]
    while len(tags) < 13:
        tags.append(product_type[:20])
    data["tags"] = tags

    # cena w zakresie
    lo, hi = PRICE_RANGES.get(product_type, (8.0, 15.0))
    try:
        price = float(data.get("price_suggestion", _price(product_type, size)))
    except (TypeError, ValueError):
        price = _price(product_type, size)
    data["price_suggestion"] = round(max(lo, min(hi, price)), 2)

    # opis min 300 słów (tylko ostrzeżenie – nie modyfikujemy)
    words = len(str(data.get("description", "")).split())
    if words < 300:
        log.warning("Description too short: %d words (min 300)", words)

    return data


# ── główna funkcja ───────────────────────────────────────────────────────────

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
        anthropic.APIError: błąd API
        ValueError: nie można sparsować odpowiedzi JSON
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill in the key.")

    product_type = product_type.lower().strip()
    size = size.upper().strip()

    if product_type not in PRICE_RANGES:
        raise ValueError(f"Unknown product_type '{product_type}'. Choose from: {list(PRICE_RANGES)}")

    if size not in SIZE_MULTIPLIER:
        raise ValueError(f"Unknown size '{size}'. Choose from: {list(SIZE_MULTIPLIER)}")

    slug = _slugify(f"{topic}-{product_type}-{size}")
    log.info("Generating listing: topic=%r type=%s size=%s slug=%s", topic, product_type, size, slug)

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(topic, product_type, size)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as e:
        log.error("Anthropic API error %s: %s", e.status_code, e.message)
        raise

    raw = message.content[0].text

    try:
        data = _parse_response(raw)
    except json.JSONDecodeError as e:
        log.error("Failed to parse model response as JSON: %s\nRaw:\n%s", e, raw[:500])
        raise ValueError(f"Model returned invalid JSON: {e}") from e

    data = _validate(data, topic, product_type, size)

    result = {
        "slug": slug,
        "topic": topic,
        "product_type": product_type,
        "size": size,
        **data,
    }

    # zapis do data/products/{slug}/listing.json
    out_dir = DATA_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "listing.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    log.info("Saved listing to %s", out_file)

    return result
