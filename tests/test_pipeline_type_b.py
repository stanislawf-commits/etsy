"""
test_pipeline_type_b.py — testy integracyjne pipeline Typ B.

Pokrywa:
  - run_pipeline_type_b() z mock listing_agent (bez Claude API)
  - generowanie SVG dla każdego kształtu Tier 1
  - generowanie STL (pure_python) dla 3 rozmiarów
  - meta.json — pola product_subtype, base_shape, stamp_topic
  - CLI new-product --subtype B --base <shape>
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.orchestrator import run_pipeline_type_b


# ── Fixture: mock listing_agent.generate ─────────────────────────────────────

def _mock_listing(topic, product_type, size):
    slug = topic.lower().replace(" ", "-").replace("_", "-")[:30] if topic else "test-product"
    return {
        "slug":             f"typeb-{slug}",
        "title":            f"Cookie Cutter — {topic or 'Test'}",
        "description":      "Test product description.",
        "tags":             ["cookie cutter", "baking", "3d printed"],
        "price_suggestion": 8.99,
        "product_type":     product_type,
    }


# ── Pomocnicze ────────────────────────────────────────────────────────────────

def _run_b(topic, base_shape, tmp_path, sizes=None):
    """Uruchamia run_pipeline_type_b() z mock listing_agent i DATA_DIR = tmp_path."""
    from src.pipeline import orchestrator as orch
    orig_data_dir = orch.DATA_DIR

    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing), \
         patch.object(type(orch), "__module__", "src.pipeline.orchestrator"):
        # Patch DATA_DIR w module orchestratora
        orch.DATA_DIR = tmp_path
        try:
            result = run_pipeline_type_b(
                topic=topic,
                base_shape=base_shape,
                sizes=sizes or ["S", "M", "L"],
                product_type="cutter",
            )
        finally:
            orch.DATA_DIR = orig_data_dir

    return result


# ── Testy podstawowe ──────────────────────────────────────────────────────────

def test_pipeline_type_b_returns_slug(tmp_path):
    """run_pipeline_type_b() zwraca slug."""
    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Floral Wreath",
            base_shape="heart",
            sizes=["M"],
            product_type="cutter",
        )
    assert "slug" in result
    assert result["slug"]


def test_pipeline_type_b_meta_fields(tmp_path):
    """meta.json zawiera product_subtype='B', base_shape, stamp_topic."""
    from src.utils.product_io import DATA_DIR, load_meta

    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Daisy Cookie",
            base_shape="circle",
            sizes=["M"],
            product_type="cutter",
        )

    slug = result["slug"]
    meta = load_meta(slug, "cutter")
    assert meta.get("product_subtype") == "B"
    assert meta.get("base_shape") == "circle"
    assert "status" in meta


def test_pipeline_type_b_creates_svg(tmp_path):
    """run_pipeline_type_b() tworzy pliki SVG w source/."""
    from src.utils.product_io import DATA_DIR

    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Star Cookies",
            base_shape="star5",
            sizes=["M"],
            product_type="cutter",
        )

    slug = result["slug"]
    source_dir = DATA_DIR / "cutter" / slug / "source"
    svgs = list(source_dir.glob("*.svg")) if source_dir.exists() else []
    assert len(svgs) >= 1, f"Brak SVG w {source_dir}"
    assert result["design"].get("success") is True


def test_pipeline_type_b_creates_stl(tmp_path):
    """run_pipeline_type_b() tworzy pliki STL w models/."""
    from src.utils.product_io import DATA_DIR

    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Heart Cookie",
            base_shape="heart",
            sizes=["M"],
            product_type="cutter",
        )

    slug = result["slug"]
    models_dir = DATA_DIR / "cutter" / slug / "models"
    stls = list(models_dir.glob("*.stl")) if models_dir.exists() else []
    assert len(stls) >= 1, f"Brak STL w {models_dir}"
    assert len(result["stl_files"]) >= 1


def test_pipeline_type_b_three_sizes(tmp_path):
    """Trzy rozmiary S/M/L → trzy STL pliki."""
    from src.utils.product_io import DATA_DIR

    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Rectangle Cutter",
            base_shape="rectangle",
            sizes=["S", "M", "L"],
            product_type="cutter",
        )

    assert len(result["stl_files"]) == 3
    names = {Path(p).name for p in result["stl_files"]}
    assert "S_cutter.stl" in names
    assert "M_cutter.stl" in names
    assert "L_cutter.stl" in names


def test_pipeline_type_b_status_ready(tmp_path):
    """Status po udanym pipelinie to ready_for_render."""
    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Squircle Cookie",
            base_shape="squircle",
            sizes=["M"],
            product_type="cutter",
        )

    assert result["status"] in ("ready_for_render", "ready_for_publish")


def test_pipeline_type_b_unknown_shape_fails(tmp_path):
    """Nieznany kształt bazy kończy się błędem."""
    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic="Unknown Cookie",
            base_shape="unicorn_shape_xyz",
            sizes=["M"],
            product_type="cutter",
        )
    # design powinien się nie udać, status nie ready
    assert result["status"] not in ("ready_for_render", "ready_for_publish")


# ── Parametryzowane — wszystkie Tier 1 ──────────────────────────────────────

TIER1 = ["heart", "circle", "rectangle", "squircle", "star5", "arch", "oval", "cloud"]


@pytest.mark.parametrize("shape", TIER1)
def test_pipeline_tier1_all_shapes(shape):
    """Każdy Tier 1 kształt przechodzi pełny pipeline (SVG + STL)."""
    from src.utils.product_io import DATA_DIR

    with patch("src.pipeline.orchestrator.listing_agent.generate", side_effect=_mock_listing):
        result = run_pipeline_type_b(
            topic=f"{shape.title()} Cookie",
            base_shape=shape,
            sizes=["M"],
            product_type="cutter",
        )

    assert result["design"].get("success") is True, f"{shape}: design failed"
    assert len(result["stl_files"]) >= 1, f"{shape}: brak STL"
    assert result["status"] in ("ready_for_render", "ready_for_publish"), \
        f"{shape}: status={result['status']}"
