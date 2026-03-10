"""
test_design_agent.py — testy src/agents/design_agent.py

Testy jednostkowe (bez API) sprawdzają:
- Generatory ścieżek SVG (mock shapes)
- Walidację ścieżki
- Detekcję kształtu z tematu
- Zapis pliku SVG + metadanych
- Nazwy plików (v3: S.svg / M.svg / L.svg)
- Strukturę katalogów (v3: {type}/{slug}/source/)
"""
import math
import re
from pathlib import Path

import pytest

from src.agents.design_agent import (
    _detect_shape,
    _validate_path,
    _path_floral,
    _path_heart,
    _path_star,
    _path_mountain,
    _path_mushroom,
    _path_leaf,
    _path_butterfly,
    _path_hexagon,
    _path_sun,
    _path_pumpkin,
    _path_christmas_tree,
    _path_snowflake,
    _path_gingerbread,
    _path_rounded_rect,
    SHAPE_BUILDERS,
    SIZE_MM,
    create_design_agent,
)


# ── _detect_shape ─────────────────────────────────────────────────────────────

def test_detect_floral():
    assert _detect_shape("floral wreath") == "floral"
    assert _detect_shape("rose cutter") == "floral"
    assert _detect_shape("daisy pattern") == "floral"


def test_detect_heart():
    assert _detect_shape("heart romantic") == "heart"
    assert _detect_shape("valentine love") == "heart"


def test_detect_star():
    assert _detect_shape("celestial star") == "star"


def test_detect_moon():
    assert _detect_shape("crescent moon") == "moon"


def test_detect_mountain():
    assert _detect_shape("alpine mountain peak") == "mountain"


def test_detect_pumpkin():
    assert _detect_shape("halloween pumpkin") == "pumpkin"


def test_detect_christmas_tree():
    assert _detect_shape("christmas tree") == "christmas_tree"
    assert _detect_shape("xmas pine cutter") == "christmas_tree"


def test_detect_snowflake():
    assert _detect_shape("snowflake winter") == "snowflake"


def test_detect_gingerbread():
    assert _detect_shape("gingerbread man") == "gingerbread"


def test_detect_fallback():
    assert _detect_shape("random unknown topic xyz") == "rounded_rect"


# ── _validate_path ────────────────────────────────────────────────────────────

def test_validate_ok_simple():
    # Czworokąt (4 punkty)
    ok, msg = _validate_path("M 10,10 L 65,10 L 65,65 L 10,65 Z", 75.0)
    assert ok, msg


def test_validate_must_start_with_M():
    ok, msg = _validate_path("L 10,10 Z", 75.0)
    assert not ok
    assert "M" in msg


def test_validate_must_end_with_Z():
    ok, msg = _validate_path("M 10,10 L 65,10 L 37,65", 75.0)
    assert not ok
    assert "Z" in msg


def test_validate_rejects_multiple_subpaths():
    # Dwie ścieżki
    ok, msg = _validate_path("M 10,10 L 20,10 Z M 30,30 L 40,30 Z", 75.0)
    assert not ok
    assert "subpath" in msg.lower() or "M" in msg


def test_validate_rejects_too_few_points():
    ok, msg = _validate_path("M 10,10 L 20,20 Z", 75.0)
    assert not ok
    assert "few" in msg.lower() or "coordinate" in msg.lower()


def test_validate_rejects_out_of_bounds():
    ok, msg = _validate_path("M 10,10 L 200,10 L 37,65 L 50,50 L 40,40 L 30,30 Z", 75.0)
    assert not ok
    assert "out of bounds" in msg.lower() or "200" in msg


def test_validate_accepts_floral_path():
    cx, cy, s = 37.5, 37.5, 37.5 * 0.46
    path_d = _path_floral(cx, cy, s)
    ok, msg = _validate_path(path_d, 75.0)
    assert ok, f"Floral path failed validation: {msg}\nPath: {path_d[:200]}"


def test_validate_accepts_heart_path():
    cx, cy, s = 37.5, 37.5, 37.5 * 0.46
    path_d = _path_heart(cx, cy, s)
    ok, msg = _validate_path(path_d, 75.0)
    assert ok, f"Heart path failed validation: {msg}"


# ── generatory kształtów — poprawność struktury ───────────────────────────────

@pytest.mark.parametrize("shape_name", list(SHAPE_BUILDERS.keys()))
def test_shape_starts_with_M_ends_with_Z(shape_name):
    cx, cy, s = 37.5, 37.5, 17.25
    path_d = SHAPE_BUILDERS[shape_name](cx, cy, s)
    d_upper = path_d.strip().upper()
    assert d_upper.startswith("M"), f"{shape_name}: path doesn't start with M"
    assert d_upper.rstrip().endswith("Z"), f"{shape_name}: path doesn't end with Z"


@pytest.mark.parametrize("shape_name", list(SHAPE_BUILDERS.keys()))
def test_shape_single_subpath(shape_name):
    """Wszystkie kształty mock muszą być pojedynczą ścieżką (jedno M na początku)."""
    cx, cy, s = 37.5, 37.5, 17.25
    path_d = SHAPE_BUILDERS[shape_name](cx, cy, s)
    # Liczymy M poza pierwszym znakiem
    subsequent = re.findall(r"(?<=[^A-Za-z])M\s", path_d.upper()[2:])
    assert not subsequent, (
        f"{shape_name}: multiple subpaths detected — "
        f"found additional M commands: {subsequent}"
    )


@pytest.mark.parametrize("shape_name", list(SHAPE_BUILDERS.keys()))
def test_shape_passes_full_validation(shape_name):
    """Wszystkie kształty mock muszą przejść pełną walidację _validate_path."""
    size_mm = 75.0
    cx = cy = size_mm / 2
    s  = size_mm * 0.46
    path_d = SHAPE_BUILDERS[shape_name](cx, cy, s)
    ok, msg = _validate_path(path_d, size_mm)
    assert ok, f"{shape_name}: {msg}\nPath: {path_d[:300]}"


# ── _path_floral — specyficznie ───────────────────────────────────────────────

def test_floral_no_degenerate_arcs():
    """Floral path nie może zawierać zdegenerowanych łuków A."""
    cx, cy, s = 37.5, 37.5, 17.25
    path_d = _path_floral(cx, cy, s)
    # Nie powinno być komendy A w ścieżce floral (używamy Q)
    assert " A " not in path_d.upper(), "Floral path should use Q/C, not A arcs"


def test_floral_uses_bezier():
    """Floral path musi używać krzywych Beziera (Q lub C)."""
    cx, cy, s = 37.5, 37.5, 17.25
    path_d = _path_floral(cx, cy, s)
    assert "Q " in path_d or "C " in path_d, "Floral path must use Bezier curves"


def test_floral_has_enough_points():
    cx, cy, s = 37.5, 37.5, 17.25
    path_d = _path_floral(cx, cy, s)
    coords = re.findall(r"-?\d+\.?\d*,-?\d+\.?\d*", path_d)
    assert len(coords) >= 12, f"Floral path has too few points: {len(coords)}"


# ── DesignAgent.generate — mock mode ─────────────────────────────────────────

def test_mock_generates_svg_file(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="floral wreath",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert result["success"]
    assert len(result["files"]) == 1
    svg_path = Path(result["files"][0]["path"])
    assert svg_path.exists()
    content = svg_path.read_text()
    assert "<path" in content
    assert "<svg" in content


def test_mock_v3_filename(tmp_path):
    """Plik SVG musi mieć nazwę {SIZE}.svg (np. M.svg), nie slug-M.svg."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="floral wreath",
        product_type="cutter",
        sizes=["S", "M", "L"],
        output_dir=tmp_path,
    )
    for file_info in result["files"]:
        fname = Path(file_info["path"]).name
        assert fname in ("S.svg", "M.svg", "L.svg"), (
            f"Expected short filename like M.svg, got: {fname}"
        )


def test_mock_v3_directory_structure(tmp_path):
    """Katalog source musi być w {output_dir}/{product_type}/{slug}/source/."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="hearts romantic",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    slug = result["slug"]
    expected_dir = tmp_path / "cutter" / slug / "source"
    assert expected_dir.is_dir(), f"Expected source dir: {expected_dir}"
    assert (expected_dir / "M.svg").exists()


def test_mock_design_json_v3(tmp_path):
    """design.json musi być w {output_dir}/{product_type}/{slug}/design.json."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="pumpkin halloween",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    slug = result["slug"]
    design_json = tmp_path / "cutter" / slug / "design.json"
    assert design_json.exists(), f"design.json not found at: {design_json}"


def test_mock_all_sizes(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="star",
        product_type="cutter",
        sizes=["XS", "S", "M", "L", "XL"],
        output_dir=tmp_path,
    )
    assert result["success"]
    assert len(result["files"]) == 5
    sizes_found = {f["size"] for f in result["files"]}
    assert sizes_found == {"XS", "S", "M", "L", "XL"}


def test_mock_unknown_size_skipped(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="leaf",
        product_type="cutter",
        sizes=["M", "XXXL"],
        output_dir=tmp_path,
    )
    assert result["success"]  # M succeeded
    assert len(result["files"]) == 1
    assert "errors" in result
    assert any("XXXL" in e for e in result["errors"])


def test_mock_correct_size_mm(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="mountain",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert result["files"][0]["width_mm"] == SIZE_MM["M"]
    assert result["files"][0]["height_mm"] == SIZE_MM["M"]


def test_mock_stamp_mode(tmp_path):
    """Stamp product_type musi generować SVG z fill (nie stroke only)."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="heart",
        product_type="stamp",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert result["success"]
    svg_content = Path(result["files"][0]["path"]).read_text()
    assert 'fill="#2d2d2d"' in svg_content


def test_mock_result_has_slug(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="floral wreath",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert result["slug"] == "floral-wreath"


def test_mock_custom_slug(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="floral wreath",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
        slug="custom-slug",
    )
    assert result["slug"] == "custom-slug"
    assert (tmp_path / "cutter" / "custom-slug" / "source" / "M.svg").exists()


# ── auto mode fallback ────────────────────────────────────────────────────────

def test_auto_falls_back_to_mock_without_key(tmp_path, monkeypatch):
    """Auto mode bez klucza API musi używać mock (nie crashować)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = create_design_agent("auto")
    result = agent.generate(
        topic="snowflake winter",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert result["success"]
    assert len(result["files"]) == 1
