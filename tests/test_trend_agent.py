"""
test_trend_agent.py — testy src/agents/trend_agent.py
"""
import pytest
from unittest.mock import patch

from src.agents.trend_agent import suggest, _suggest_static, _infer_product_type
from src.utils.config_loader import cfg


def test_suggest_returns_list():
    result = suggest()
    assert isinstance(result, list)
    assert len(result) > 0


def test_suggest_count():
    count = cfg("trends")["strategy"]["suggestions_count"]
    result = suggest()
    assert len(result) == count


def test_suggest_topic_fields():
    result = suggest()
    for item in result:
        assert "topic" in item
        assert "product_type" in item
        assert "priority" in item
        assert item["product_type"] in ("cutter", "stamp", "set")


def test_static_fallback():
    result = _suggest_static(5)
    assert len(result) == 5
    for item in result:
        assert "topic" in item


def test_pytrends_fallback_when_unavailable(monkeypatch):
    """Gdy pytrends jest niedostępny, powinien użyć static."""
    monkeypatch.setitem(__builtins__ if isinstance(__builtins__, dict) else vars(__builtins__),
                       "x", None)  # nie blokujemy importu tak
    # Prostszy sposób: mockujemy _suggest_pytrends żeby zwracała None
    with patch("src.agents.trend_agent._suggest_pytrends", return_value=None):
        result = suggest()
        assert len(result) > 0
        # Wszystkie powinny mieć source=static
        sources = [r.get("source", "static") for r in result]
        assert all(s == "static" for s in sources)


def test_infer_product_type_stamp():
    assert _infer_product_type("botanical leaf stamp") == "stamp"
    assert _infer_product_type("emboss pattern") == "stamp"


def test_infer_product_type_set():
    assert _infer_product_type("christmas set") == "set"
    assert _infer_product_type("cookie bundle") == "set"


def test_infer_product_type_default_cutter():
    assert _infer_product_type("snowflake") == "cutter"
    assert _infer_product_type("heart shape") == "cutter"


def test_suggest_saves_log(tmp_path, monkeypatch):
    """suggest() zapisuje plik JSON do logs/."""
    import src.agents.trend_agent as mod
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    suggest()
    log_file = tmp_path / "trend_suggestions.json"
    assert log_file.exists()
    import json
    data = json.loads(log_file.read_text())
    assert "suggestions" in data
    assert "generated_at" in data
