"""
test_daily_trend_scan.py — testy run_scan (mock pipeline + trend_agent).
"""
import pytest
from unittest.mock import patch, MagicMock


FAKE_SUGGESTIONS = [
    {"topic": "Christmas Stars",  "product_type": "cutter", "size": "M"},
    {"topic": "Easter Bunny",     "product_type": "cutter", "size": "M"},
    {"topic": "Halloween Ghost",  "product_type": "stamp",  "size": "S"},
    {"topic": "Valentines Heart", "product_type": "cutter", "size": "L"},
]

FAKE_PIPELINE_RESULT = {
    "slug":             "christmas-stars-cutter-m",
    "title":            "Christmas Stars Cookie Cutter",
    "price_suggestion": 4.99,
    "status":           "ready_for_publish",
}


@pytest.fixture(autouse=True)
def _patch_write_log(monkeypatch):
    """Wyłącz zapis pliku log."""
    monkeypatch.setattr("src.jobs.daily_trend_scan._write_log", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _patch_record(monkeypatch):
    """Wyłącz zapis do DB."""
    monkeypatch.setattr("src.jobs.daily_trend_scan._record_auto_draft", lambda *a, **kw: None)


def test_creates_up_to_max_new():
    with patch("src.jobs.daily_trend_scan.trend_agent") as mock_trend, \
         patch("src.jobs.daily_trend_scan.run_pipeline", return_value=FAKE_PIPELINE_RESULT), \
         patch("src.jobs.daily_trend_scan._get_existing_topics", return_value=set()):
        mock_trend.suggest.return_value = FAKE_SUGGESTIONS
        from src.jobs.daily_trend_scan import run_scan
        result = run_scan(max_new=2)

    assert result["created"] == 2
    assert result["errors"] == 0


def test_dry_run_does_not_call_pipeline():
    with patch("src.jobs.daily_trend_scan.trend_agent") as mock_trend, \
         patch("src.jobs.daily_trend_scan.run_pipeline") as mock_pipe, \
         patch("src.jobs.daily_trend_scan._get_existing_topics", return_value=set()):
        mock_trend.suggest.return_value = FAKE_SUGGESTIONS[:2]
        from src.jobs.daily_trend_scan import run_scan
        result = run_scan(max_new=5, dry_run=True)

    mock_pipe.assert_not_called()
    assert result["created"] == 2


def test_skips_duplicate_topics():
    existing = {"christmas stars", "easter bunny"}
    with patch("src.jobs.daily_trend_scan.trend_agent") as mock_trend, \
         patch("src.jobs.daily_trend_scan.run_pipeline", return_value=FAKE_PIPELINE_RESULT) as mock_pipe, \
         patch("src.jobs.daily_trend_scan._get_existing_topics", return_value=existing):
        mock_trend.suggest.return_value = FAKE_SUGGESTIONS
        from src.jobs.daily_trend_scan import run_scan
        result = run_scan(max_new=5)

    assert result["skipped"] == 2
    assert mock_pipe.call_count == 2  # tylko 2 nowe (Halloween + Valentines)


def test_handles_pipeline_error():
    with patch("src.jobs.daily_trend_scan.trend_agent") as mock_trend, \
         patch("src.jobs.daily_trend_scan.run_pipeline", side_effect=Exception("Claude down")), \
         patch("src.jobs.daily_trend_scan._get_existing_topics", return_value=set()):
        mock_trend.suggest.return_value = FAKE_SUGGESTIONS[:1]
        from src.jobs.daily_trend_scan import run_scan
        result = run_scan(max_new=3)

    assert result["errors"] == 1
    assert result["created"] == 0


def test_max_new_cap_respected():
    with patch("src.jobs.daily_trend_scan.trend_agent") as mock_trend, \
         patch("src.jobs.daily_trend_scan.run_pipeline", return_value=FAKE_PIPELINE_RESULT) as mock_pipe, \
         patch("src.jobs.daily_trend_scan._get_existing_topics", return_value=set()):
        mock_trend.suggest.return_value = FAKE_SUGGESTIONS  # 4 sugestie
        from src.jobs.daily_trend_scan import run_scan
        run_scan(max_new=1)

    assert mock_pipe.call_count == 1  # max_new=1 zatrzymuje po pierwszym
