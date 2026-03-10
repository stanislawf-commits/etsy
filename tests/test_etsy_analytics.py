"""
test_etsy_analytics.py — testy fetch_listing_stats (mock requests).
"""
import pytest
from unittest.mock import patch, MagicMock

from src.utils.etsy_analytics import fetch_listing_stats


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch):
    """Wyłącz time.sleep żeby testy były szybkie."""
    monkeypatch.setattr("src.utils.etsy_analytics.time.sleep", lambda _: None)


def _mock_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from requests import HTTPError
        resp.raise_for_status.side_effect = HTTPError(f"{status_code}")
    return resp


def test_fetch_returns_views_and_favorites():
    with patch("src.utils.etsy_analytics.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"views": 42, "num_favorers": 7})
        result = fetch_listing_stats("123", shop_id="shop1", access_token="tok")
    assert result == {"views": 42, "favorites": 7}


def test_fetch_404_returns_zeros():
    with patch("src.utils.etsy_analytics.requests.get") as mock_get:
        mock_get.return_value = _mock_response(404, {})
        result = fetch_listing_stats("999", shop_id="shop1", access_token="tok")
    assert result == {"views": 0, "favorites": 0}


def test_fetch_403_returns_zeros():
    with patch("src.utils.etsy_analytics.requests.get") as mock_get:
        mock_get.return_value = _mock_response(403, {})
        result = fetch_listing_stats("999", shop_id="shop1", access_token="tok")
    assert result == {"views": 0, "favorites": 0}


def test_fetch_500_raises():
    with patch("src.utils.etsy_analytics.requests.get") as mock_get:
        mock_get.return_value = _mock_response(500, {})
        with pytest.raises(Exception):
            fetch_listing_stats("123", shop_id="shop1", access_token="tok")


def test_correct_url_called():
    with patch("src.utils.etsy_analytics.requests.get") as mock_get:
        mock_get.return_value = _mock_response(200, {"views": 0, "num_favorers": 0})
        fetch_listing_stats("456", shop_id="MYSHOP", access_token="TOKEN")
    url = mock_get.call_args[0][0]
    assert "MYSHOP" in url
    assert "456" in url
    assert "stats" in url
