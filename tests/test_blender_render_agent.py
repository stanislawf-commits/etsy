"""
test_blender_render_agent.py — testy src/agents/blender_render_agent.py
"""
import shutil
from pathlib import Path

import pytest

from src.agents.blender_render_agent import create_blender_render_agent

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def agent():
    return create_blender_render_agent()


def test_agent_initializes(agent):
    assert agent is not None


def test_blender_detected(agent):
    """Blender 4.x jest dostępny w systemie."""
    assert agent._blender_bin is not None, "Blender not found — install blender package"


def test_find_stl_files(tmp_path, agent):
    """_find_stl_files wykrywa STL po konwencji nazewniczej."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    slug = "test-cutter-m"
    (models_dir / f"{slug}_M_cutter.stl").write_bytes(b"x" * 1000)
    (models_dir / f"{slug}_S_cutter.stl").write_bytes(b"x" * 1000)

    stl_files = agent._find_stl_files(models_dir, slug, "cutter")
    assert "M" in stl_files
    assert "S" in stl_files


def test_find_stl_files_missing_dir(tmp_path, agent):
    result = agent._find_stl_files(tmp_path / "nonexistent", "slug", "cutter")
    assert result == {}


def test_pillow_fallback(tmp_path, agent, monkeypatch):
    """Gdy brak Blendera, używa Pillow fallback."""
    monkeypatch.setattr(agent, "_blender_bin", None)

    product_dir = tmp_path / "test-cutter-m"
    product_dir.mkdir()
    (product_dir / "source").mkdir()
    (product_dir / "models").mkdir()
    (product_dir / "renders").mkdir()

    # Kopiuj SVG jako placeholder
    shutil.copy(FIXTURES / "sample_design.svg", product_dir / "source" / "test-cutter-m-M.svg")

    import json, shutil as sh
    listing = json.loads((FIXTURES / "sample_listing.json").read_text())
    listing["slug"] = "test-cutter-m"
    (product_dir / "listing.json").write_text(json.dumps(listing))

    result = agent.generate(
        product_dir=product_dir,
        slug="test-cutter-m",
        topic="test",
        product_type="cutter",
    )
    assert result["engine"] == "pillow"


@pytest.mark.blender
def test_full_render_blender(tmp_path, agent):
    """Test pełnego renderowania Blenderem (wymaga prawdziwego STL)."""
    real_product = Path("data/products/floral-wreath-cutter-m")
    if not real_product.exists() or not list((real_product / "models").glob("*.stl")):
        pytest.skip("Real product STL not available")

    result = agent.generate(
        product_dir=real_product,
        slug="floral-wreath-cutter-m",
        topic="floral wreath",
        product_type="cutter",
    )

    assert result["engine"] == "blender"
    assert result["success"] is True
    assert len(result["renders"]) == 5

    for render_path in result["renders"]:
        p = Path(render_path)
        assert p.exists()
        assert p.stat().st_size > 10_000, f"Render too small: {p.name}"
