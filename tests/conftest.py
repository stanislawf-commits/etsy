"""
conftest.py — wspólne fixtures dla wszystkich testów etsy3d.
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_listing() -> dict:
    """Przykładowy listing.json."""
    return json.loads((FIXTURES_DIR / "sample_listing.json").read_text())


@pytest.fixture
def sample_meta() -> dict:
    """Przykładowy meta.json."""
    return json.loads((FIXTURES_DIR / "sample_meta.json").read_text())


@pytest.fixture
def sample_svg_path() -> Path:
    """Ścieżka do przykładowego SVG."""
    return FIXTURES_DIR / "sample_design.svg"


@pytest.fixture
def tmp_product_dir(tmp_path: Path) -> Path:
    """Tymczasowy katalog produktu z przykładowymi plikami."""
    slug = "test-cutter-m"
    product_dir = tmp_path / slug
    product_dir.mkdir()
    (product_dir / "source").mkdir()
    (product_dir / "models").mkdir()
    (product_dir / "renders").mkdir()

    # Kopiuj fixture SVG
    shutil.copy(FIXTURES_DIR / "sample_design.svg", product_dir / "source" / f"{slug}-M.svg")
    shutil.copy(FIXTURES_DIR / "sample_design.svg", product_dir / "source" / f"{slug}-S.svg")
    shutil.copy(FIXTURES_DIR / "sample_design.svg", product_dir / "source" / f"{slug}-L.svg")

    # Zapisz listing.json i meta.json
    listing = json.loads((FIXTURES_DIR / "sample_listing.json").read_text())
    listing["slug"] = slug
    (product_dir / "listing.json").write_text(json.dumps(listing))

    meta = json.loads((FIXTURES_DIR / "sample_meta.json").read_text())
    meta["slug"] = slug
    (product_dir / "meta.json").write_text(json.dumps(meta))

    return product_dir


@pytest.fixture
def mock_anthropic(monkeypatch):
    """Mockuje anthropic.Anthropic() — brak realnych wywołań API."""
    import anthropic

    class FakeContent:
        text = json.dumps({
            "title": "Test Cookie Cutter 3D Printed Food Safe PLA Medium 7-8cm",
            "description": " ".join(["word"] * 310),  # > 300 słów
            "tags": [f"tag{i}" for i in range(13)],
            "price_suggestion": 11.99,
        })

    class FakeUsage:
        input_tokens = 100
        output_tokens = 200

    class FakeResponse:
        content = [FakeContent()]
        usage = FakeUsage()

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr("src.utils.claude_client._client", lambda: FakeClient())
    return FakeClient()
