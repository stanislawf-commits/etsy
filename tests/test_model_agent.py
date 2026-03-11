"""
test_model_agent.py — testy src/agents/model_agent.py
"""
import struct
from pathlib import Path

import pytest

from src.agents.model_agent import (
    SVGPathParser,
    STLValidator,
    PurePythonSTLWriter,
    create_model_agent,
    _size_mm_map,
    _cutter_cfg,
    BEZIER_SAMPLES,
)


FIXTURES = Path(__file__).parent / "fixtures"


# ── SVGPathParser ─────────────────────────────────────────────────────────────

def test_parser_reads_circle():
    svg = '<svg width="75mm" height="75mm" viewBox="0 0 750 750"><circle cx="375" cy="375" r="300"/></svg>'
    parser = SVGPathParser()
    contours = parser.parse(svg)
    assert len(contours) >= 1
    # Koło powinno mieć punkty rozmieszczone dookoła
    c = contours[0]
    assert len(c) >= 16


def test_parser_reads_path():
    svg = '<svg width="75mm" viewBox="0 0 750 750"><path d="M100,100 L200,100 L150,200 Z"/></svg>'
    parser = SVGPathParser()
    contours = parser.parse(svg)
    assert len(contours) >= 1
    assert len(contours[0]) >= 3


def test_parser_reads_fixture_svg():
    svg_path = FIXTURES / "sample_design.svg"
    parser = SVGPathParser()
    contours = parser.parse(svg_path.read_text())
    assert len(contours) >= 1


def test_parser_empty_svg():
    svg = '<svg width="75mm" viewBox="0 0 750 750"></svg>'
    parser = SVGPathParser()
    contours = parser.parse(svg)
    assert contours == []


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
    """Tworzy minimalny prawidłowy binarny STL i waliduje."""
    stl_path = tmp_path / "test.stl"
    writer = PurePythonSTLWriter()
    # Prosty trójkąt jako kontur
    contour = [(0, 0), (10, 0), (5, 10)]
    cfg_dict = {"total_height": 12.0, "base_thick": 4.0,
                "wall_thick": 1.8, "cutting_edge": 0.4, "relief_height": 1.5}
    writer.generate_cutter_stl(contour, cfg_dict, stl_path)

    v = STLValidator()
    result = v.validate(stl_path, cfg_dict)
    assert result["valid"] is True
    assert result["n_triangles"] >= 10
    assert result["stl_format"] == "binary"


# ── Size map ──────────────────────────────────────────────────────────────────

def test_size_mm_map_from_config():
    mm = _size_mm_map()
    assert "M" in mm
    assert mm["M"] == 75.0
    assert mm["S"] == 60.0
    assert mm["L"] == 90.0


def test_cutter_cfg_has_required_fields():
    c = _cutter_cfg()
    assert "wall_thickness" in c
    assert "blade_thickness" in c
    assert "total_height" in c
    assert "base_height" in c


# ── ModelAgent.generate (pure_python) ────────────────────────────────────────

def test_generate_missing_svg(tmp_path):
    agent = create_model_agent("pure_python")
    result = agent.generate(
        svg_path=tmp_path / "nonexistent.svg",
        product_type="cutter",
        size_key="M",
        output_dir=tmp_path,
    )
    assert result["valid"] is False
    assert "not found" in result["error"].lower()


def test_generate_cutter_from_fixture(tmp_path):
    svg_path = FIXTURES / "sample_design.svg"
    agent = create_model_agent("pure_python")
    result = agent.generate(
        svg_path=svg_path,
        product_type="cutter",
        size_key="M",
        output_dir=tmp_path,
    )
    assert result["valid"] is True
    assert result["n_triangles"] >= 10
    assert Path(result["stl_path"]).exists()
    assert result["size_mm"] == 75.0


def test_generate_stamp_from_fixture(tmp_path):
    svg_path = FIXTURES / "sample_design.svg"
    agent = create_model_agent("pure_python")
    result = agent.generate(
        svg_path=svg_path,
        product_type="stamp",
        size_key="M",
        output_dir=tmp_path,
    )
    assert result["valid"] is True
    assert Path(result["stl_path"]).exists()


# ── Faza 6 Sprint 1: ear-clipping, Shapely offset, Bézier, taper/fillet ───────

def test_earclip_convex():
    """Kwadrat (4 wierzchołki) → 2 trójkąty."""
    writer = PurePythonSTLWriter()
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    triangles = writer._earclip_triangulate(square)
    assert len(triangles) == 2
    # Każdy trójkąt to 3 indeksy
    for tri in triangles:
        assert len(tri) == 3


def test_earclip_concave():
    """Gwiazda 5-ramienna (wklęsła) → triangulacja bez samoprzecięć."""
    import math
    writer = PurePythonSTLWriter()
    # 5-ramienna gwiazda: naprzemienne punkty na R_outer i R_inner
    R_outer, R_inner, n = 50.0, 20.0, 5
    pts = []
    for i in range(n * 2):
        angle = math.pi * i / n - math.pi / 2
        r = R_outer if i % 2 == 0 else R_inner
        pts.append((r * math.cos(angle), r * math.sin(angle)))

    triangles = writer._earclip_triangulate(pts)
    assert len(triangles) == len(pts) - 2  # n-2 trójkątów dla wielokątu prostego
    # Każdy indeks musi być w zakresie
    for tri in triangles:
        for idx in tri:
            assert 0 <= idx < len(pts)


def test_shapely_offset_star():
    """Offset gwiazdy ±2mm — Shapely buffer daje inny kontur niż oryginał."""
    import math
    writer = PurePythonSTLWriter()
    R_outer, R_inner, n = 30.0, 12.0, 5
    pts = []
    for i in range(n * 2):
        angle = math.pi * i / n - math.pi / 2
        r = R_outer if i % 2 == 0 else R_inner
        pts.append((r * math.cos(angle), r * math.sin(angle)))

    offset_out = writer._offset_contour(pts, 2.0)
    offset_in  = writer._offset_contour(pts, -2.0)
    assert offset_out != pts
    assert offset_in  != pts
    assert len(offset_out) >= 3
    assert len(offset_in)  >= 3


def test_bezier_samples():
    """Parser cubic Bézier → ≥ BEZIER_SAMPLES punktów na krzywą."""
    # Jedna krzywa C z M startowego → powinno dodać BEZIER_SAMPLES punktów
    svg = (
        '<svg width="75mm" viewBox="0 0 750 750">'
        '<path d="M 0,0 C 100,0 200,200 300,200 Z"/>'
        '</svg>'
    )
    parser = SVGPathParser()
    contours = parser.parse(svg)
    assert len(contours) >= 1
    # Kontur: 1 punkt M + BEZIER_SAMPLES punktów z C ≥ 32
    total_pts = sum(len(c) for c in contours)
    assert total_pts >= BEZIER_SAMPLES


def test_taper_stl_geometry(tmp_path):
    """Generuj cutter z taper+fillet — plik >84 bytes, valid=True."""
    stl_path = tmp_path / "taper_test.stl"
    writer = PurePythonSTLWriter()
    contour = [(0, 0), (20, 0), (20, 20), (0, 20)]
    cfg_dict = {
        "total_height": 12.0,
        "base_thick":   4.0,
        "wall_thick":   1.8,
        "cutting_edge": 0.4,
        "relief_height": 1.5,
        "taper_height": 3.0,
        "fillet_top":   1.0,
    }
    n_tri = writer.generate_cutter_stl(contour, cfg_dict, stl_path)
    assert stl_path.exists()
    assert stl_path.stat().st_size > 84
    assert n_tri > 0
    v = STLValidator()
    result = v.validate(stl_path, cfg_dict)
    assert result["valid"] is True


def test_generate_cutter_concave_shape(tmp_path):
    """Snowflake SVG (kształt wklęsły) → valid STL."""
    svg_path = FIXTURES / "snowflake.svg"
    agent = create_model_agent("pure_python")
    result = agent.generate(
        svg_path=svg_path,
        product_type="cutter",
        size_key="M",
        output_dir=tmp_path,
    )
    assert result["valid"] is True, f"STL invalid: {result.get('error')}"
    assert result["n_triangles"] > 0
    assert Path(result["stl_path"]).exists()


def test_generate_all(tmp_path):
    """generate_all() generuje cutter+stamp dla wszystkich rozmiarów."""
    slug = "test-cutter"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    import shutil
    for size in ["S", "M", "L"]:
        # Nowe nazewnictwo: S.svg, M.svg, L.svg
        shutil.copy(FIXTURES / "sample_design.svg", source_dir / f"{size}.svg")

    agent = create_model_agent("pure_python")
    result = agent.generate_all(
        slug=slug,
        source_dir=source_dir,
        output_dir=tmp_path / "models",
    )
    assert len(result["sizes"]) >= 3
    assert len(result["stl_files"]) >= 6  # 3 rozmiary × 2 typy
    for size_key, types in result["sizes"].items():
        assert "cutter" in types
        assert "stamp" in types
        assert types["cutter"]["valid"] is True, f"Cutter {size_key}: {types['cutter'].get('error')}"
        assert types["stamp"]["valid"] is True, f"Stamp {size_key}: {types['stamp'].get('error')}"


def test_generate_all_single_type(tmp_path):
    """generate_all() z product_type generuje tylko jeden typ."""
    slug = "test-cutter"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    import shutil
    shutil.copy(FIXTURES / "sample_design.svg", source_dir / "M.svg")

    agent = create_model_agent("pure_python")
    result = agent.generate_all(
        slug=slug,
        source_dir=source_dir,
        output_dir=tmp_path / "models",
        product_type="cutter",
    )
    assert "M" in result["sizes"]
    assert "cutter" in result["sizes"]["M"]
    assert "stamp" not in result["sizes"]["M"]
    assert len(result["stl_files"]) == 1


def test_stl_naming_convention(tmp_path):
    """STL nazywa się {SIZE}_{product_type}.stl (np. M_cutter.stl)."""
    svg_path = FIXTURES / "sample_design.svg"
    agent = create_model_agent("pure_python")
    result = agent.generate(svg_path, "cutter", "M", tmp_path)
    assert result["valid"] is True
    stl_path = Path(result["stl_path"])
    assert stl_path.name == "M_cutter.stl"
