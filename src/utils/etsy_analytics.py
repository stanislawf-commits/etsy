"""
etsy_analytics.py — pobieranie statystyk listingów z Etsy API v3.

Endpoint: GET /v3/application/shops/{shop_id}/listings/{listing_id}/stats
Scope wymagany: listings_r (już w config/etsy.yaml)

Użycie:
    from src.utils.etsy_analytics import fetch_listing_stats

    stats = fetch_listing_stats(
        listing_id="123456789",
        shop_id=os.getenv("ETSY_SHOP_ID"),
        access_token=os.getenv("ETSY_ACCESS_TOKEN"),
    )
    # {"views": 42, "favorites": 7}
"""
import logging
import time

import requests

from src.utils.config_loader import cfg

log = logging.getLogger(__name__)


def fetch_listing_stats(
    listing_id: str,
    *,
    shop_id: str,
    access_token: str,
) -> dict:
    """
    Pobiera views + favorites dla jednego listingu z Etsy API v3.

    Returns:
        {"views": int, "favorites": int}
        Zwraca zera przy 404 (listing niedostępny/usunięty).

    Raises:
        requests.HTTPError  dla kodów 4xx/5xx innych niż 404.
    """
    etsy_cfg = cfg("etsy")
    base_url = etsy_cfg["api"]["base_url"]
    rps      = etsy_cfg["api"].get("requests_per_second", 5)

    url = f"{base_url}/application/shops/{shop_id}/listings/{listing_id}/stats"
    headers = {
        "x-api-key":     "",          # nie wymagany gdy Bearer token
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json",
    }

    # Prosty throttle (nie pełny rate-limiter)
    time.sleep(1.0 / rps)

    resp = requests.get(url, headers=headers, timeout=15)

    if resp.status_code == 404:
        log.warning("Listing %s not found (404) — returning zeros", listing_id)
        return {"views": 0, "favorites": 0}

    if resp.status_code == 403:
        log.warning("Listing %s stats forbidden (403) — plan may not include analytics", listing_id)
        return {"views": 0, "favorites": 0}

    resp.raise_for_status()

    data = resp.json()
    return {
        "views":     data.get("views", 0),
        "favorites": data.get("num_favorers", 0),
    }
