"""
etsy_webhook.py — odbiornik zdarzeń Etsy (sprzedaż → aktualizacja stanu).

Etsy wysyła POST na /etsy/webhook przy zdarzeniu RECEIPT_PAID.
Serwer weryfikuje HMAC-SHA256, parsuje payload, aktualizuje DB.

Uruchomienie:
    python cli.py webhook-serve [--port 8765]

ENV wymagane:
    ETSY_WEBHOOK_SECRET  — sekret HMAC z panelu Etsy Developer
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger(__name__)


# ── Parsowanie i obsługa zdarzeń ─────────────────────────────────────────────

def parse_sale_event(payload: dict) -> dict | None:
    """
    Parsuje payload webhooka Etsy.
    Zwraca {"listing_id": str, "quantity": int} lub None jeśli to nie sprzedaż.
    """
    event_type = payload.get("type", "")
    if event_type != "RECEIPT_PAID":
        return None

    # Każda receipt może zawierać wiele transactions
    transactions = payload.get("receipt", {}).get("transactions", [])
    if not transactions:
        return None

    # Agreguj qty per listing_id
    sales: dict[str, int] = {}
    for tx in transactions:
        lid = str(tx.get("listing_id", ""))
        qty = int(tx.get("quantity", 1))
        if lid:
            sales[lid] = sales.get(lid, 0) + qty

    if not sales:
        return None

    # Zwracamy pierwszą sprzedaną pozycję (multi-item obsługujemy przez wiele wywołań)
    listing_id, quantity = next(iter(sales.items()))
    return {"listing_id": listing_id, "quantity": quantity, "all_sales": sales}


def handle_sale(payload: dict) -> dict:
    """
    Główny handler: parse → znajdź produkt → zaktualizuj stan → zapisz StockEvent.

    Returns:
        {"slug": str|None, "action": str, "restock_needed": bool}
    """
    from src.db.session import get_session
    from src.db.models import Product, StockEvent
    from sqlmodel import select

    sale = parse_sale_event(payload)
    if sale is None:
        log.info("webhook: ignoring non-sale event type=%s", payload.get("type"))
        return {"slug": None, "action": "ignored", "restock_needed": False}

    all_sales = sale.get("all_sales", {sale["listing_id"]: sale["quantity"]})
    restock_needed = False
    processed_slugs = []

    for listing_id, quantity in all_sales.items():
        slug = _find_slug_by_listing_id(listing_id)
        if slug is None:
            log.warning("webhook: unknown listing_id=%s — no matching product", listing_id)
            continue

        with get_session() as session:
            product = session.exec(select(Product).where(Product.slug == slug)).first()
            if product is None:
                log.warning("webhook: product %s not found in DB", slug)
                continue

            product.stock_quantity = max(0, product.stock_quantity - quantity)
            product.last_sold_at   = datetime.now(timezone.utc)

            session.add(StockEvent(
                slug=slug,
                event_type="sale",
                quantity=quantity,
                source="webhook",
                payload=json.dumps({"listing_id": listing_id, "quantity": quantity}),
            ))

            needs_restock = product.stock_quantity <= product.restock_threshold
            if needs_restock:
                restock_needed = True

            log.info("webhook: sale recorded slug=%s qty=%d stock_now=%d",
                     slug, quantity, product.stock_quantity)

        if needs_restock:
            _handle_restock(slug)

        processed_slugs.append(slug)

    return {
        "slug":           processed_slugs[0] if processed_slugs else None,
        "slugs":          processed_slugs,
        "action":         "sale_recorded",
        "restock_needed": restock_needed,
    }


def _find_slug_by_listing_id(listing_id: str) -> str | None:
    """Szuka produktu w DB po etsy_listing_id."""
    try:
        from src.db.session import get_session
        from src.db.models import Product
        from sqlmodel import select
        with get_session() as session:
            product = session.exec(
                select(Product).where(Product.etsy_listing_id == listing_id)
            ).first()
            return product.slug if product else None
    except Exception as exc:
        log.error("_find_slug_by_listing_id error: %s", exc)
        return None


def _handle_restock(slug: str) -> None:
    """Deleguje do restock_alert.run_check() dla konkretnego slug."""
    try:
        from src.jobs.restock_alert import _in_cooldown, _record_event, _trigger_reprint
        from src.utils.config_loader import cfg

        restock_cfg = cfg("etsy").get("restock", {})
        action      = restock_cfg.get("action", "log_only")
        cooldown_h  = restock_cfg.get("cooldown_hours", 24)

        if _in_cooldown(slug, cooldown_h):
            return

        _record_event(slug, "restock_alert", 0)
        log.warning("RESTOCK ALERT: %s — stock low", slug)

        if action == "auto_reprint":
            from src.db.session import get_session
            from src.db.models import Product
            from sqlmodel import select
            with get_session() as session:
                prod = session.exec(select(Product).where(Product.slug == slug)).first()
                if prod:
                    prod_data = prod.model_dump()
            _trigger_reprint(slug, prod_data)
    except Exception as exc:
        log.error("_handle_restock error for %s: %s", slug, exc)


# ── HTTP Server ───────────────────────────────────────────────────────────────

class _WebhookHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler dla webhooków Etsy."""

    def do_POST(self):  # noqa: N802
        if self.path != "/etsy/webhook":
            self._respond(404, "Not Found")
            return

        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length)
        sig_hdr = self.headers.get("X-Etsy-Signature", "")

        if not _verify_signature(body, sig_hdr):
            log.warning("webhook: invalid signature — rejecting request")
            self._respond(401, "Unauthorized")
            return

        try:
            payload = json.loads(body)
            result  = handle_sale(payload)
            log.info("webhook: handled — %s", result)
            self._respond(200, "OK")
        except Exception as exc:
            log.error("webhook: handler error: %s", exc)
            self._respond(200, "OK")  # Zawsze 200 — Etsy nie będzie retryować

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._respond(200, "etsy3d webhook OK")
        else:
            self._respond(404, "Not Found")

    def _respond(self, code: int, message: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(message.encode())

    def log_message(self, fmt, *args):  # noqa: N802
        log.debug("HTTP %s", fmt % args)


def _verify_signature(body: bytes, header_sig: str) -> bool:
    """Weryfikuje HMAC-SHA256 podpis Etsy."""
    secret = os.getenv("ETSY_WEBHOOK_SECRET", "")
    if not secret:
        log.warning("ETSY_WEBHOOK_SECRET not set — skipping signature verification")
        return True  # Bezpieczniej byłoby False, ale ułatwia dev setup

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig)


def start_server(port: int | None = None) -> None:
    """Uruchamia HTTP serwer webhooków (blokujący)."""
    from src.utils.config_loader import cfg
    from src.db.session import init_db

    init_db()

    if port is None:
        port = cfg("etsy")["api"].get("webhook_port", 8765)

    server = HTTPServer(("0.0.0.0", port), _WebhookHandler)
    log.info("Webhook server started on port %d", port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Webhook server stopped")
        server.server_close()
