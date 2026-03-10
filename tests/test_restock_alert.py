"""
test_restock_alert.py — testy run_check (mock DB).
"""
import pytest
from unittest.mock import patch, MagicMock


PROD_LOW_STOCK = {
    "slug":             "roses-cutter-m",
    "topic":            "roses",
    "product_type":     "cutter",
    "size":             "M",
    "status":           "listed",
    "stock_quantity":   2,
    "restock_threshold": 3,
}


@pytest.fixture(autouse=True)
def _patch_record(monkeypatch):
    monkeypatch.setattr("src.jobs.restock_alert._record_event", lambda *a, **kw: None)


def test_no_low_stock_returns_zeros():
    with patch("src.jobs.restock_alert.init_db"), \
         patch("src.jobs.restock_alert.get_session") as mock_sess:
        mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock(
            exec=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)
        from src.jobs.restock_alert import run_check
        result = run_check()
    assert result == {"alerts": 0, "reprints_triggered": 0, "checked": 0}


def test_dry_run_does_not_record():
    with patch("src.jobs.restock_alert.init_db"), \
         patch("src.jobs.restock_alert.get_session") as mock_sess, \
         patch("src.jobs.restock_alert._in_cooldown", return_value=False), \
         patch("src.jobs.restock_alert._record_event") as mock_record:
        mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock(
            exec=MagicMock(return_value=MagicMock(
                all=MagicMock(return_value=[MagicMock(model_dump=MagicMock(return_value=PROD_LOW_STOCK))])
            ))
        ))
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)
        from src.jobs.restock_alert import run_check
        result = run_check(dry_run=True)
    mock_record.assert_not_called()
    assert result["alerts"] == 1


def test_cooldown_skips_alert():
    with patch("src.jobs.restock_alert.init_db"), \
         patch("src.jobs.restock_alert.get_session") as mock_sess, \
         patch("src.jobs.restock_alert._in_cooldown", return_value=True):
        mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock(
            exec=MagicMock(return_value=MagicMock(
                all=MagicMock(return_value=[MagicMock(model_dump=MagicMock(return_value=PROD_LOW_STOCK))])
            ))
        ))
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)
        from src.jobs.restock_alert import run_check
        result = run_check()
    assert result["alerts"] == 0  # cooldown aktywny


def test_in_cooldown_true_when_recent_event():
    """_in_cooldown zwraca True gdy jest niedawny restock_alert."""
    mock_event = MagicMock()
    with patch("src.jobs.restock_alert.get_session") as mock_sess:
        mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock(
            exec=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_event)))
        ))
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)
        from src.jobs.restock_alert import _in_cooldown
        assert _in_cooldown("test-slug", 24) is True


def test_in_cooldown_false_when_no_event():
    with patch("src.jobs.restock_alert.get_session") as mock_sess:
        mock_sess.return_value.__enter__ = MagicMock(return_value=MagicMock(
            exec=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
        ))
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)
        from src.jobs.restock_alert import _in_cooldown
        assert _in_cooldown("test-slug", 24) is False
