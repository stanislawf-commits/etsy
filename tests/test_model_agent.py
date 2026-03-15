"""
test_model_agent.py — testy src/agents/model_agent.py (Typ B pipeline).

Pokrywa:
  - STLValidator: brak pliku, za mały, poprawny binarny STL
  - PurePythonSTLWriter: earclip, offset, generacja cutter/stamp
  - ModelAgent.generate_type_b(): cutter i stamp z Shapely Polygon
  - Pomocnicze: _size_mm_map, _cutter_cfg
"""
import struct
from pathlib import Path

import pytest

from src.agents.model_agent import (
    STLValidator,
    PurePythonSTLWriter,
    create_model_agent,
    _size_mm_map,
    _cutter_cfg,
)
from src.shapes.base_shapes import get_base


FIXTURES = Path(__file__).parent / "fixtures"


# ── STLValidator ──────────────────────────────────────────────────────────────

def test_validator_missing_file(tmp_path):
    v = STLValidator()
    result = v.validate(tmp_path / "nonexistent.stl", {})
    assert result["valid"] is False
    assert "does not exist" in result["error"]


def test_validator_too_small(tmp_path):
    f = tmp_path / "tiny.stl"
    f.write_bytes(b"too small")
    v = STLValidator()
    result = v.validate(f, {})
    assert result["valid"] is False


def test_validator_valid_binary_stl(tmp_path):
    stl_path = tmp_path / "test.stl"
    writer = PurePythonSTLWriter()
    contour = [(0, 0), (10, 0), (5, 10)]
    cfg_dict = {"total_height": 12.0, "base_thick": 4.0,
                "wall_thick": 1.8, "cutting_edge": 0.4,
                "relief_height": 1.5, "taper_height": 3.0}
    writer.generate_cutter_stl(contour, cfg_dict, stl_path)
    v = STLValidator()
    result = v.validate(stl_path, cfg_dict)
    assert result["valid"] is True
    assert result["n_triangles"] >= 10
    assert result["stl_format"] == "binary"


# ── PurePythonSTLWriter ───────────────────────────────────────────────────────

def test_earclip_convex():
    """Kwadrat → 2 trójkąty."""
    writer = PurePythonSTLWriter()
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    triangles = writer._earclip_triangulate(square)
    assert len(triangles) == 2
    for tri in triangles:
        assert len(tri) == 3


def test_earclip_concave():
    """Gwiazda 5-ramienna (wklęsła) → poprawna triangulacja."""
    import math
    writer = PurePythonSTLWriter()
    R_outer, R_inner, n = 50.0, 20.0, 5
    pts = []
    for i in range(n * 2):
        angle = math.pi * i / n - math.pi / 2
        r = R_outer if i % 2 == 0 else R_inner
        pts.append((r * math.cos(angle), r * math.sin(angle)))
    triangles = writer._earclip_triangulate(pts)
    assert len(triangles) == len(pts) - 2
    for tri in triangles:
        for idx in tri:
            assert 0 <= idx < len(pts)


def test_shapely_offset():
    """Offset konturu ±2mm przez Shapely zwraca inny kontur."""
    import math
    writer = PurePythonSTLWriter()
    pts = [(10 * math.cos(2 * math.pi * i / 32),
            10 * math.sin(2 * math.pi * i / 32)) for i in range(32)]
    outer = writer._offset_contour(pts, 2.0)
    inner = writer._offset_contour(pts, -2.0)
    assert outer != pts
    assert inner != pts
    assert len(outer) >= 3
    assert len(inner) >= 3


def test_taper_stl_valid(tmp_path):
    """Cutter z taper — plik >84B, valid=True."""
    stl_path = tmp_path / "taper_test.stl"
    writer = PurePythonSTLWriter()
    contour = [(0, 0), (20, 0), (20, 20), (0, 20)]
    cfg_dict = {"total_height": 12.0, "base_thick": 4.0,
                "wall_thick": 1.8, "cutting_edge": 0.4,
                "relief_height": 1.5, "taper_height": 3.0}
    n_tri = writer.generate_cutter_stl(contour, cfg_dict, stl_path)
    assert stl_path.exists()
    assert stl_path.stat().st_size > 84
    assert n_tri > 0
    v = STLValidator()
    result = v.validate(stl_path, cfg_dict)
    assert result["valid"] is True


# ── Config helpers ─────────────────────────────────────────────────────────────

def test_size_mm_map_has_standard_sizes():
    mm = _size_mm_map()
    assert mm["M"] == 75.0
    assert mm["S"] == 60.0
    assert mm["L"] == 90.0


def test_cutter_cfg_has_required_fields():
    c = _cutter_cfg()
    assert "wall_thickness" in c
    assert "blade_thickness" in c
    assert "total_height" in c
    assert "base_height" in c


# ── ModelAgent.generate_type_b ─────────────────────────────────────────────────

def test_generate_type_b_cutter(tmp_path):
    """generate_type_b() tworzy valid STL cuttera z Shapely Polygon."""
    poly = get_base("heart", 75.0)
    agent = create_model_agent("pure_python")
    result = agent.generate_type_b(
        base_poly=poly,
        size_mm=75.0,
        product_type="cutter",
        output_dir=tmp_path,
        size_key="M",
    )
    assert result["valid"] is True, f"STL invalid: {result.get('error')}"
    assert result["n_triangles"] >= 10
    assert Path(result["stl_path"]).exists()
    assert Path(result["stl_path"]).name == "M_cutter.stl"
    assert result["size_mm"] == 75.0


def test_generate_type_b_stl_naming(tmp_path):
    """Nazwa pliku STL: {size_key}_{product_type}.stl."""
    poly = get_base("circle", 60.0)
    agent = create_model_agent("pure_python")
    result = agent.generate_type_b(poly, 60.0, "cutter", tmp_path, size_key="S")
    assert Path(result["stl_path"]).name == "S_cutter.stl"


def test_generate_type_b_no_size_key(tmp_path):
    """Bez size_key plik STL nazywa się {product_type}.stl."""
    poly = get_base("circle", 75.0)
    agent = create_model_agent("pure_python")
    result = agent.generate_type_b(poly, 75.0, "cutter", tmp_path)
    assert Path(result["stl_path"]).name == "cutter.stl"


def test_generate_type_b_stamp_requires_stamp_poly(tmp_path):
    """Stamp bez stamp_poly → error."""
    poly = get_base("heart", 75.0)
    agent = create_model_agent("pure_python")
    result = agent.generate_type_b(poly, 75.0, "stamp", tmp_path)
    assert result["valid"] is False
    assert "stamp_poly" in result["error"]


def test_generate_type_b_stamp_with_stamp_poly(tmp_path):
    """Stamp z stamp_poly → valid STL."""
    base = get_base("heart", 75.0)
    stamp = get_base("circle", 40.0)
    agent = create_model_agent("pure_python")
    result = agent.generate_type_b(
        base_poly=base,
        size_mm=75.0,
        product_type="stamp",
        output_dir=tmp_path,
        size_key="M",
        stamp_poly=stamp,
    )
    assert result["valid"] is True
    assert Path(result["stl_path"]).name == "M_stamp.stl"


@pytest.mark.parametrize("shape", ["heart", "circle", "rectangle", "squircle"])
def test_generate_type_b_tier1_shapes(tmp_path, shape):
    """Wszystkie podstawowe Tier 1 shapes dają valid STL."""
    poly = get_base(shape, 75.0)
    agent = create_model_agent("pure_python")
    result = agent.generate_type_b(poly, 75.0, "cutter", tmp_path, size_key="M")
    assert result["valid"] is True, f"{shape}: {result.get('error')}"
    assert result["n_triangles"] > 0


def test_generate_type_b_all_sizes(tmp_path):
    """generate_type_b_all() generuje STL dla każdego rozmiaru."""
    poly = get_base("heart", 75.0)
    agent = create_model_agent("pure_python")
    sizes = {"S": 60.0, "M": 75.0, "L": 90.0}
    result = agent.generate_type_b_all(
        base_poly=poly,
        slug="heart-test",
        output_dir=tmp_path,
        sizes=sizes,
        product_type="cutter",
    )
    assert len(result["sizes"]) == 3
    assert len(result["stl_files"]) == 3
    for size_key in ["S", "M", "L"]:
        assert result["sizes"][size_key]["cutter"]["valid"] is True
