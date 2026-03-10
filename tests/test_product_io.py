"""
test_product_io.py — testy src/utils/product_io.py
"""
import json
from pathlib import Path

import pytest

from src.utils import product_io


@pytest.fixture(autouse=True)
def patch_data_dir(tmp_path, monkeypatch):
    """Przekieruj DATA_DIR na tymczasowy katalog."""
    monkeypatch.setattr(product_io, "DATA_DIR", tmp_path)


def test_save_and_load_meta(tmp_path):
    meta = {"id": "abc", "slug": "test-slug", "status": "draft"}
    product_io.save_meta("test-slug", meta)
    loaded = product_io.load_meta("test-slug")
    assert loaded["id"] == "abc"
    assert loaded["status"] == "draft"
    assert "updated_at" in loaded  # save_meta dodaje updated_at


def test_load_meta_missing_returns_empty():
    result = product_io.load_meta("nonexistent-slug-xyz")
    assert result == {}


def test_update_meta():
    product_io.save_meta("slug-x", {"status": "draft"})
    updated = product_io.update_meta("slug-x", status="listed", etsy_id=42)
    assert updated["status"] == "listed"
    assert updated["etsy_id"] == 42

    # Sprawdź że zapis faktycznie trafił do pliku
    reloaded = product_io.load_meta("slug-x")
    assert reloaded["status"] == "listed"


def test_mark_step_done_idempotent():
    product_io.save_meta("slug-y", {"steps_completed": []})
    product_io.mark_step_done("slug-y", "listing")
    product_io.mark_step_done("slug-y", "listing")  # drugi raz — brak duplikatu
    meta = product_io.load_meta("slug-y")
    assert meta["steps_completed"].count("listing") == 1


def test_is_step_done():
    product_io.save_meta("slug-z", {"steps_completed": ["listing", "design"]})
    assert product_io.is_step_done("slug-z", "listing") is True
    assert product_io.is_step_done("slug-z", "render") is False


def test_save_and_load_listing():
    listing = {"slug": "test", "title": "Test Cookie Cutter", "tags": ["a", "b"]}
    product_io.save_listing("test", listing)
    loaded = product_io.load_listing("test")
    assert loaded["title"] == "Test Cookie Cutter"
    assert loaded["tags"] == ["a", "b"]


def test_load_listing_missing_returns_empty():
    result = product_io.load_listing("no-such-slug-xyz")
    assert result == {}


def test_list_all_slugs(tmp_path):
    for slug in ["alpha", "beta", "gamma"]:
        product_io.save_meta(slug, {"slug": slug, "status": "draft"})
    slugs = product_io.list_all_slugs()
    assert set(slugs) >= {"alpha", "beta", "gamma"}


def test_list_by_status(tmp_path):
    product_io.save_meta("pub-1", {"slug": "pub-1", "status": "listed"})
    product_io.save_meta("draft-1", {"slug": "draft-1", "status": "draft"})
    listed = product_io.list_by_status("listed")
    assert "pub-1" in listed
    assert "draft-1" not in listed


def test_ensure_product_dir_creates_dir(tmp_path):
    d = product_io.ensure_product_dir("new-product-slug")
    assert d.exists()
    assert d.is_dir()
