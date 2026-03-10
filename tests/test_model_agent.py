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


def test_generate_all(tmp_path):
    """generate_all() przetwarza wszystkie rozmiary z katalogu source."""
    slug = "test-cutter"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    import shutil
    for size in ["S", "M", "L"]:
        shutil.copy(FIXTURES / "sample_design.svg", source_dir / f"{slug}-{size}.svg")

    agent = create_model_agent("pure_python")
    result = agent.generate_all(
        slug=slug,
        product_type="cutter",
        source_dir=source_dir,
        output_dir=tmp_path / "models",
    )
    assert len(result["sizes"]) >= 3
    for size_key, r in result["sizes"].items():
        assert r["valid"] is True, f"Size {size_key} failed: {r.get('error')}"
