"""
test_config_loader.py — testy src/utils/config_loader.py
"""
import pytest
from src.utils.config_loader import cfg, reload


def test_pricing_loads():
    pricing = cfg("pricing")
    assert "product_types" in pricing
    assert "cutter" in pricing["product_types"]
    assert "stamp" in pricing["product_types"]
    assert "set" in pricing["product_types"]


def test_pricing_values():
    p = cfg("pricing")["product_types"]["cutter"]
    assert p["price_min"] > 0
    assert p["price_max"] > p["price_min"]


def test_size_multipliers():
    mults = cfg("pricing")["size_multipliers"]
    assert "M" in mults
    assert mults["M"] == 1.0
    assert mults["XS"] < 1.0
    assert mults["XL"] > 1.0


def test_etsy_loads():
    etsy = cfg("etsy")
    assert etsy["listing"]["taxonomy_id"] == 68887614
    assert etsy["listing"]["tags_count"] == 13
    assert etsy["listing"]["title_max_chars"] == 140


def test_etsy_images():
    images = cfg("etsy")["images"]
    order = images["upload_order"]
    assert len(order) == 5
    assert "hero" in order
    assert order[0] == "hero"


def test_product_types_loads():
    pt = cfg("product_types")
    assert "cutter" in pt
    assert "stamp" in pt
    cutter = pt["cutter"]
    assert "wall_thickness" in cutter
    assert "sizes" in cutter
    assert "M" in cutter["sizes"]


def test_trends_loads():
    t = cfg("trends")
    assert "topics" in t
    evergreen = t["topics"]["evergreen"]
    assert len(evergreen) >= 5
    for topic in evergreen:
        assert "topic" in topic
        assert "product_type" in topic


def test_missing_config_raises():
    with pytest.raises(FileNotFoundError):
        reload("nonexistent_config_xyz")


def test_cache_works():
    """cfg() zwraca ten sam obiekt przy kolejnych wywołaniach."""
    a = cfg("pricing")
    b = cfg("pricing")
    assert a is b  # lru_cache zwraca ten sam obiekt
