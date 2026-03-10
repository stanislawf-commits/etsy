"""
Testy dla listing_agent.

Testy jednostkowe (bez API) sprawdzają pomocnicze funkcje.
Test integracyjny (wymaga ANTHROPIC_API_KEY) uruchamia pełny generate().
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from src.agents.listing_agent import (
    _price,
    _slugify,
    _validate,
    generate,
    PRICE_RANGES,
    SIZE_MULTIPLIER,
)


# ── unit tests ───────────────────────────────────────────────────────────────

def test_slugify_basic():
    assert _slugify("Floral Wreath") == "floral-wreath"

def test_slugify_special_chars():
    # & i ! są usuwane; nadmiarowe myślniki są kompresowane do jednego
    assert _slugify("mountains & climbing!") == "mountains-climbing"

def test_price_in_range():
    for ptype, (lo, hi) in PRICE_RANGES.items():
        for size in SIZE_MULTIPLIER:
            p = _price(ptype, size)
            assert lo <= p <= hi + 5, f"{ptype}/{size}: {p} out of expected range"

def test_price_ends_in_99():
    p = _price("cutter", "M")
    assert str(p).endswith(".99"), f"Expected .99 ending, got {p}"

def test_validate_title_truncated():
    data = {"title": "A" * 200, "tags": ["tag"] * 13, "price_suggestion": 10.0, "description": "x " * 310}
    result = _validate(data, "topic", "cutter", "M")
    assert len(result["title"]) <= 140

def test_validate_tags_padded():
    data = {"title": "Test", "tags": ["tag1", "tag2"], "price_suggestion": 10.0, "description": "x " * 310}
    result = _validate(data, "topic", "cutter", "M")
    assert len(result["tags"]) == 13

def test_validate_tags_trimmed():
    data = {"title": "Test", "tags": ["tag"] * 20, "price_suggestion": 10.0, "description": "x " * 310}
    result = _validate(data, "topic", "cutter", "M")
    assert len(result["tags"]) == 13

def test_validate_tag_max_length():
    data = {"title": "Test", "tags": ["averylongtagname123456"] * 13, "price_suggestion": 10.0, "description": "x " * 310}
    result = _validate(data, "topic", "cutter", "M")
    for tag in result["tags"]:
        assert len(tag) <= 20

def test_validate_price_clamped():
    data = {"title": "Test", "tags": ["t"] * 13, "price_suggestion": 999.0, "description": "x " * 310}
    result = _validate(data, "topic", "cutter", "M")
    lo, hi = PRICE_RANGES["cutter"]
    assert result["price_suggestion"] <= hi

def test_generate_bad_type():
    with pytest.raises(ValueError, match="Unknown product_type"):
        generate("topic", product_type="unknown", size="M")

def test_generate_bad_size():
    with pytest.raises(ValueError, match="Unknown size"):
        generate("topic", product_type="cutter", size="GIANT")

def test_generate_no_api_key():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
        # patch load_dotenv so it doesn't override our empty key
        with patch("src.agents.listing_agent.os.getenv", return_value=""):
            with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
                generate("topic", product_type="cutter", size="M")


# ── integration test (skipped when no key) ───────────────────────────────────

@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
def test_generate_integration(tmp_path, monkeypatch):
    """Wywołuje prawdziwe API i sprawdza strukturę odpowiedzi."""
    import src.agents.listing_agent as agent_mod
    monkeypatch.setattr(agent_mod, "DATA_DIR", tmp_path)

    result = generate("floral wreath", product_type="cutter", size="M")

    assert result["slug"]
    assert len(result["title"]) <= 140
    assert len(result["tags"]) == 13
    assert all(len(t) <= 20 for t in result["tags"])
    lo, hi = PRICE_RANGES["cutter"]
    assert lo <= result["price_suggestion"] <= hi
    assert len(result["description"].split()) >= 300

    out = tmp_path / result["slug"] / "listing.json"
    assert out.exists()
    saved = json.loads(out.read_text())
    assert saved["title"] == result["title"]
