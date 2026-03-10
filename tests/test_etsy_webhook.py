"""
test_etsy_webhook.py — testy parse_sale_event, handle_sale, _verify_signature.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


RECEIPT_PAID_PAYLOAD = {
    "type": "RECEIPT_PAID",
    "receipt": {
        "receipt_id": "12345",
        "transactions": [
            {"listing_id": "111222333", "quantity": 2},
        ],
    },
}


def test_parse_sale_event_receipt_paid():
    from src.webhooks.etsy_webhook import parse_sale_event
    result = parse_sale_event(RECEIPT_PAID_PAYLOAD)
    assert result is not None
    assert result["listing_id"] == "111222333"
    assert result["quantity"] == 2


def test_parse_sale_event_ignores_other_types():
    from src.webhooks.etsy_webhook import parse_sale_event
    result = parse_sale_event({"type": "LISTING_CREATED"})
    assert result is None


def test_parse_sale_event_empty_transactions():
    from src.webhooks.etsy_webhook import parse_sale_event
    result = parse_sale_event({"type": "RECEIPT_PAID", "receipt": {"transactions": []}})
    assert result is None


def test_verify_signature_no_secret(monkeypatch):
    """Bez sekretu — przepuszcza (dev mode)."""
    monkeypatch.setenv("ETSY_WEBHOOK_SECRET", "")
    from src.webhooks.etsy_webhook import _verify_signature
    assert _verify_signature(b"body", "wrong") is True


def test_verify_signature_valid(monkeypatch):
    import hashlib, hmac as _hmac
    secret = "mysecret"
    body   = b'{"type":"RECEIPT_PAID"}'
    sig    = _hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("ETSY_WEBHOOK_SECRET", secret)
    from importlib import reload
    import src.webhooks.etsy_webhook as mod
    assert mod._verify_signature(body, sig) is True


def test_verify_signature_invalid(monkeypatch):
    monkeypatch.setenv("ETSY_WEBHOOK_SECRET", "mysecret")
    import src.webhooks.etsy_webhook as mod
    assert mod._verify_signature(b"body", "badsignature") is False


def test_handle_sale_unknown_listing():
    with patch("src.webhooks.etsy_webhook._find_slug_by_listing_id", return_value=None):
        from src.webhooks.etsy_webhook import handle_sale
        result = handle_sale(RECEIPT_PAID_PAYLOAD)
    # Nie crashuje, slug=None
    assert result["slug"] is None


def test_handle_sale_ignored_event():
    from src.webhooks.etsy_webhook import handle_sale
    result = handle_sale({"type": "LISTING_CREATED"})
    assert result["action"] == "ignored"
