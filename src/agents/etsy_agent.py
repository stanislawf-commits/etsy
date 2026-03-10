"""
etsy_agent.py — publikuje listing produktu na Etsy via API v3.

Tryby:
  - dry-run:  brak ETSY_API_KEY → zapisuje listing_export.json
  - oauth:    ETSY_API_KEY + brak ETSY_ACCESS_TOKEN → prosi o etsy-auth
  - publish:  ETSY_API_KEY + ETSY_ACCESS_TOKEN → publikuje na Etsy
"""
import base64
import hashlib
import json
import logging
import os
import secrets
import urllib.parse
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ETSY_BASE      = "https://api.etsy.com/v3"
ETSY_AUTH_URL  = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
REDIRECT_URI   = "http://localhost:3003/callback"
SCOPES         = "listings_w transactions_r"

# Etsy Taxonomy ID dla Cookie Cutters & Stamps
TAXONOMY_ID = 68887614


class EtsyAgent:
    def __init__(self):
        self.api_key      = os.getenv("ETSY_API_KEY", "")
        self.api_secret   = os.getenv("ETSY_API_SECRET", "")
        self.shop_id      = os.getenv("ETSY_SHOP_ID", "")
        self.access_token = os.getenv("ETSY_ACCESS_TOKEN", "")

    # ── Publiczne API ──────────────────────────────────────────────────────────

    def publish(self, product_dir: str | Path, slug: str) -> dict:
        """
        Publikuje produkt na Etsy lub wykonuje dry-run.

        Zwraca: {'success': bool, 'listing_id': str|None, 'url': str|None, 'error': str|None}
        """
        product_dir = Path(product_dir)

        # Wczytaj dane produktu
        listing_path = product_dir / "listing.json"
        meta_path    = product_dir / "meta.json"

        if not listing_path.exists():
            return {"success": False, "listing_id": None, "url": None,
                    "error": f"listing.json nie istnieje: {listing_path}"}

        listing = json.loads(listing_path.read_text())
        meta    = json.loads(meta_path.read_text()) if meta_path.exists() else {}

        # ── Tryb dry-run (brak klucza API) ────────────────────────────────────
        if not self.api_key:
            return self._dry_run(product_dir, slug, listing, meta, meta_path)

        # ── Brak tokenu OAuth2 ─────────────────────────────────────────────────
        if not self.access_token:
            return {
                "success": False,
                "listing_id": None,
                "url": None,
                "error": "oauth_required",
            }

        # ── Publikacja przez Etsy API v3 ───────────────────────────────────────
        return self._publish_to_etsy(product_dir, slug, listing, meta, meta_path)

    # ── Dry-run ────────────────────────────────────────────────────────────────

    def _dry_run(
        self,
        product_dir: Path,
        slug: str,
        listing: dict,
        meta: dict,
        meta_path: Path,
    ) -> dict:
        export = self._build_listing_body(listing)
        export["_slug"]   = slug
        export["_source"] = "listing_export.json (dry-run)"

        renders_path = str(product_dir.resolve() / "renders")
        price_eur    = export.get("price", "–")
        export["manual_publish_checklist"] = {
            "step_1":      "Wejdź na etsy.com/your/listings/create",
            "step_2":      "Wklej tytuł z pola title",
            "step_3":      "Wklej opis z pola description",
            "step_4":      f"Ustaw cenę z pola price_eur ({price_eur}) EUR",
            "step_5":      "Dodaj tagi z pola tags (max 13)",
            "step_6":      "Uploaduj zdjęcia z folderu renders/ w kolejności: hero, lifestyle, sizes, detail, info",
            "step_7":      "Shipping: ustaw profil wysyłki UE",
            "step_8":      "Kliknij Publish",
            "renders_path": renders_path,
            "taxonomy_id": TAXONOMY_ID,
            "category":    "Cookie Cutters & Stamps",
        }

        export_path = product_dir / "listing_export.json"
        export_path.write_text(json.dumps(export, indent=2, ensure_ascii=False))
        log.info("Dry-run export saved: %s", export_path)

        # Aktualizuj meta
        meta.setdefault("etsy", {})
        meta["etsy"]["status"] = "dry_run"
        meta["status"] = "ready_for_manual_publish"
        if meta_path.exists():
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

        return {
            "success": True,
            "listing_id": None,
            "url": None,
            "error": None,
            "dry_run": True,
            "export_path": str(export_path),
        }

    # ── Etsy API ───────────────────────────────────────────────────────────────

    def _publish_to_etsy(
        self,
        product_dir: Path,
        slug: str,
        listing: dict,
        meta: dict,
        meta_path: Path,
    ) -> dict:
        headers = {
            "x-api-key":     self.api_key,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type":  "application/json",
        }

        # 1. Utwórz listing
        body = self._build_listing_body(listing)
        url  = f"{ETSY_BASE}/application/shops/{self.shop_id}/listings"

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            err = f"HTTP {exc.response.status_code}: {exc.response.text[:400]}"
            log.error("Create listing failed: %s", err)
            return {"success": False, "listing_id": None, "url": None, "error": err}
        except requests.RequestException as exc:
            log.error("Create listing request error: %s", exc)
            return {"success": False, "listing_id": None, "url": None, "error": str(exc)}

        data       = resp.json()
        listing_id = str(data.get("listing_id", ""))
        listing_url = f"https://www.etsy.com/listing/{listing_id}"
        log.info("Listing created: %s", listing_url)

        # 2. Upload zdjęć
        renders_dir = product_dir / "renders"
        image_names = ["hero.jpg", "lifestyle.jpg", "sizes.jpg", "detail.jpg", "info.jpg"]
        uploaded    = 0

        for rank, name in enumerate(image_names, start=1):
            img_path = renders_dir / name
            if not img_path.exists():
                log.warning("Render not found, skipping: %s", img_path)
                continue
            ok = self._upload_image(listing_id, img_path, rank)
            if ok:
                uploaded += 1

        log.info("Uploaded %d/%d images for listing %s", uploaded, len(image_names), listing_id)

        # 3. Zapisz w meta.json
        meta.setdefault("etsy", {})
        meta["etsy"]["listing_id"] = listing_id
        meta["etsy"]["url"]        = listing_url
        meta["etsy"]["status"]     = "draft"
        meta["status"]             = "listed"
        if meta_path.exists():
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

        return {
            "success":    True,
            "listing_id": listing_id,
            "url":        listing_url,
            "error":      None,
            "images":     uploaded,
        }

    def _upload_image(self, listing_id: str, img_path: Path, rank: int) -> bool:
        url = (
            f"{ETSY_BASE}/application/shops/{self.shop_id}"
            f"/listings/{listing_id}/images"
        )
        headers = {
            "x-api-key":     self.api_key,
            "Authorization": f"Bearer {self.access_token}",
        }
        try:
            with img_path.open("rb") as fh:
                resp = requests.post(
                    url,
                    headers=headers,
                    files={"image": (img_path.name, fh, "image/jpeg")},
                    data={"rank": rank},
                    timeout=60,
                )
            resp.raise_for_status()
            log.info("Image uploaded: %s (rank %d)", img_path.name, rank)
            return True
        except Exception as exc:
            log.warning("Image upload failed (%s): %s", img_path.name, exc)
            return False

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _build_listing_body(self, listing: dict) -> dict:
        tags = listing.get("tags", [])[:13]
        price = float(listing.get("price_suggestion", 9.99))

        return {
            "title":               listing.get("title", "3D Printed Product"),
            "description":         listing.get("description", ""),
            "price":               price,
            "quantity":            999,
            "who_made":            "i_did",
            "when_made":           "made_to_order",
            "taxonomy_id":         TAXONOMY_ID,
            "tags":                tags,
            "is_digital":          False,
            "should_auto_renew":   True,
            "shipping_profile_id": None,
        }

    # ── OAuth2 helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def build_auth_url() -> tuple[str, str, str]:
        """
        Buduje URL do autoryzacji OAuth2 (PKCE).
        Zwraca: (auth_url, code_verifier, state)
        """
        code_verifier  = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)

        params = {
            "response_type":         "code",
            "redirect_uri":          REDIRECT_URI,
            "scope":                 SCOPES,
            "client_id":             os.getenv("ETSY_API_KEY", ""),
            "state":                 state,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = ETSY_AUTH_URL + "?" + urllib.parse.urlencode(params)
        return auth_url, code_verifier, state

    @staticmethod
    def exchange_code(code: str, code_verifier: str) -> dict:
        """Wymienia authorization code na access_token."""
        data = {
            "grant_type":    "authorization_code",
            "client_id":     os.getenv("ETSY_API_KEY", ""),
            "redirect_uri":  REDIRECT_URI,
            "code":          code,
            "code_verifier": code_verifier,
        }
        resp = requests.post(ETSY_TOKEN_URL, data=data, timeout=30)
        resp.raise_for_status()
        return resp.json()


# ── Factory ────────────────────────────────────────────────────────────────────

def create_etsy_agent() -> EtsyAgent:
    return EtsyAgent()
