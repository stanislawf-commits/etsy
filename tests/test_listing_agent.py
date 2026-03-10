"""
test_listing_agent.py — testy src/agents/listing_agent.py

Testy jednostkowe (bez API) sprawdzają pomocnicze funkcje.
Test integracyjny (wymaga ANTHROPIC_API_KEY) uruchamia pełny generate().
"""
import json
import os
import pytest

from src.agents.listing_agent import _price, _slugify, _validate, generate
from src.utils.config_loader import cfg


# ── unit tests ───────────────────────────────────────────────────────────────

def test_slugify_basic():
    assert _slugify("Floral Wreath") == "floral-wreath"


def test_slugify_special_chars():
    assert _slugify("mountains & climbing!") == "mountains-climbing"


def test_price_ends_in_99():
    p = _price("cutter", "M")
    assert str(p).endswith(".99"), f"Expected .99 ending, got {p}"


def test_price_in_range():
    pricing = cfg("pricing")
    for pt in ["cutter", "stamp", "set"]:
        for size in ["XS", "S", "M", "L", "XL"]:
            p = _price(pt, size)
            lo = pricing["product_types"][pt]["price_min"]
            hi = pricing["product_types"][pt]["price_max"]
            assert lo * 0.85 <= p <= hi * 1.35, f"{pt}/{size}: {p} out of range [{lo},{hi}]"


def test_price_size_ordering():
    xs = _price("cutter", "XS")
    m  = _price("cutter", "M")
    xl = _price("cutter", "XL")
    assert xs <= m <= xl


def test_validate_title_truncated():
    data = {"title": "A" * 200, "tags": ["tag"] * 13, "price_suggestion": 10.0,
            "description": "word " * 310}
    result = _validate(data, "cutter", "M")
    assert len(result["title"]) <= 140


def test_validate_tags_padded_to_13():
    data = {"title": "T", "tags": ["t1", "t2"], "price_suggestion": 10.0,
            "description": "word " * 310}
    result = _validate(data, "cutter", "M")
    assert len(result["tags"]) == 13


def test_validate_tags_trimmed_to_13():
    data = {"title": "T", "tags": ["tag"] * 20, "price_suggestion": 10.0,
            "description": "word " * 310}
    result = _validate(data, "cutter", "M")
    assert len(result["tags"]) == 13


def test_validate_tag_max_20_chars():
    data = {"title": "T", "tags": ["a" * 30] * 13, "price_suggestion": 10.0,
            "description": "word " * 310}
    result = _validate(data, "cutter", "M")
    for tag in result["tags"]:
        assert len(tag) <= 20


def test_validate_price_clamped_high():
    data = {"title": "T", "tags": ["t"] * 13, "price_suggestion": 9999.0,
            "description": "word " * 310}
    result = _validate(data, "cutter", "M")
    hi = cfg("pricing")["product_types"]["cutter"]["price_max"]
    assert result["price_suggestion"] <= hi


def test_validate_price_clamped_low():
    data = {"title": "T", "tags": ["t"] * 13, "price_suggestion": 0.01,
            "description": "word " * 310}
    result = _validate(data, "cutter", "M")
    lo = cfg("pricing")["product_types"]["cutter"]["price_min"]
    assert result["price_suggestion"] >= lo


def test_generate_bad_type_raises():
    with pytest.raises(ValueError, match="Unknown product_type"):
        generate("topic", product_type="unknown", size="M")


def test_generate_bad_size_raises():
    with pytest.raises(ValueError, match="Unknown size"):
        generate("topic", product_type="cutter", size="XXXL_SUPER")


# ── mock test ─────────────────────────────────────────────────────────────────

def test_generate_with_mock(mock_anthropic, tmp_path, monkeypatch):
    """Test generate() z zamockowanym API — brak realnych wywołań."""
    from src.utils import product_io
    monkeypatch.setattr(product_io, "DATA_DIR", tmp_path)

    result = generate("floral wreath", "cutter", "M")

    assert result["slug"] == "floral-wreath-cutter-m"
    assert result["topic"] == "floral wreath"
    assert len(result["tags"]) == 13
    assert result["price_suggestion"] > 0
    # Sprawdź zapis do pliku
    assert (tmp_path / "floral-wreath-cutter-m" / "listing.json").exists()


# ── integration test (wymaga ANTHROPIC_API_KEY) ───────────────────────────────

@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
def test_generate_integration(tmp_path, monkeypatch):
    from src.utils import product_io
    monkeypatch.setattr(product_io, "DATA_DIR", tmp_path)

    result = generate("floral wreath", product_type="cutter", size="M")

    assert result["slug"]
    assert len(result["title"]) <= 140
    assert len(result["tags"]) == 13
    assert all(len(t) <= 20 for t in result["tags"])
    lo = cfg("pricing")["product_types"]["cutter"]["price_min"]
    hi = cfg("pricing")["product_types"]["cutter"]["price_max"]
    assert lo <= result["price_suggestion"] <= hi
    assert len(result["description"].split()) >= 300

    saved = json.loads((tmp_path / result["slug"] / "listing.json").read_text())
    assert saved["title"] == result["title"]
