"""
test_shapes.py — testy src/shapes/ (geometry engine Typ B).

Pokrywa:
  - base_shapes: get_base(), list_bases() — wszystkie Tier 1
  - svg_export:  base_to_svg(), poly_to_path_d()
  - scad_export: cutter_scad(), stamp_scad(), _poly_points()
"""
import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from src.shapes.base_shapes import get_base, list_bases
from src.shapes.svg_export import base_to_svg, poly_to_path_d
from src.shapes.scad_export import cutter_scad, stamp_scad, _poly_points


TIER1 = ["heart", "circle", "rectangle", "squircle", "star5", "arch", "oval", "cloud"]


# ── list_bases ────────────────────────────────────────────────────────────────

def test_list_bases_all_returns_20():
    all_shapes = list_bases()
    assert len(all_shapes) == 20


def test_list_bases_tier1_returns_8():
    t1 = list_bases(tier=1)
    assert set(t1) == set(TIER1)


def test_list_bases_tier2_returns_6():
    t2 = list_bases(tier=2)
    assert len(t2) == 6


def test_list_bases_tier3_returns_6():
    t3 = list_bases(tier=3)
    assert len(t3) == 6


# ── get_base: valid polygons ──────────────────────────────────────────────────

@pytest.mark.parametrize("name", TIER1)
def test_get_base_returns_valid_polygon(name):
    poly = get_base(name, 75.0)
    assert isinstance(poly, Polygon)
    assert poly.is_valid
    assert not poly.is_empty


@pytest.mark.parametrize("name", TIER1)
def test_get_base_centered_at_origin(name):
    """Centrum bounding box powinno być blisko (0,0)."""
    poly = get_base(name, 75.0)
    b = poly.bounds
    cx = (b[0] + b[2]) / 2
    cy = (b[1] + b[3]) / 2
    assert abs(cx) < 1.0, f"{name}: cx={cx:.2f} nie jest blisko 0"
    assert abs(cy) < 1.0, f"{name}: cy={cy:.2f} nie jest blisko 0"


@pytest.mark.parametrize("name", TIER1)
def test_get_base_max_dim_equals_size_mm(name):
    """Max wymiar bounding box powinien wynosić dokładnie size_mm."""
    size_mm = 75.0
    poly = get_base(name, size_mm)
    b = poly.bounds
    max_dim = max(b[2] - b[0], b[3] - b[1])
    assert abs(max_dim - size_mm) < 0.1, (
        f"{name}: max_dim={max_dim:.2f} ≠ {size_mm}"
    )


@pytest.mark.parametrize("size_mm", [50.0, 75.0, 90.0, 110.0])
def test_get_base_scales_correctly(size_mm):
    """get_base() skaluje do podanego rozmiaru."""
    poly = get_base("heart", size_mm)
    b = poly.bounds
    max_dim = max(b[2] - b[0], b[3] - b[1])
    assert abs(max_dim - size_mm) < 0.1


def test_get_base_rectangle_aspect_ratio():
    """Prostokąt powinien mieć aspect ratio bliski 1.4."""
    poly = get_base("rectangle", 75.0)
    b = poly.bounds
    w = b[2] - b[0]
    h = b[3] - b[1]
    ar = w / h
    assert abs(ar - 1.4) < 0.05, f"rectangle aspect_ratio={ar:.3f}"


def test_get_base_arch_is_taller_than_wide():
    """Arch (0.75 aspect) powinien być wyższy niż szerszy."""
    poly = get_base("arch", 75.0)
    b = poly.bounds
    w = b[2] - b[0]
    h = b[3] - b[1]
    assert h > w, f"arch h={h:.1f} <= w={w:.1f}"


def test_get_base_oval_is_taller_than_wide():
    """Oval (0.72 aspect) powinien być wyższy niż szerszy."""
    poly = get_base("oval", 75.0)
    b = poly.bounds
    w = b[2] - b[0]
    h = b[3] - b[1]
    assert h > w, f"oval h={h:.1f} <= w={w:.1f}"


def test_get_base_cloud_aspect_ratio():
    """Cloud powinien mieć aspect ratio bliski 1.6."""
    poly = get_base("cloud", 75.0)
    b = poly.bounds
    w = b[2] - b[0]
    h = b[3] - b[1]
    ar = w / h
    assert abs(ar - 1.6) < 0.1, f"cloud aspect_ratio={ar:.3f}"


def test_get_base_unknown_raises():
    with pytest.raises(ValueError, match="not implemented"):
        get_base("unicorn", 75.0)


def test_get_base_has_enough_points():
    """Polygon powinien mieć ≥ 32 punktów (wystarczająca gładkość)."""
    for name in TIER1:
        poly = get_base(name, 75.0)
        n = len(poly.exterior.coords) - 1  # -1 bo closing point
        assert n >= 32, f"{name}: tylko {n} punktów"


# ── svg_export ────────────────────────────────────────────────────────────────

def test_poly_to_path_d_starts_with_M():
    poly = get_base("circle", 50.0)
    d = poly_to_path_d(poly)
    assert d.startswith("M ") or d.startswith("M")


def test_poly_to_path_d_ends_with_Z():
    poly = get_base("heart", 75.0)
    d = poly_to_path_d(poly)
    assert d.strip().endswith("Z")


def test_base_to_svg_creates_file(tmp_path):
    poly = get_base("heart", 75.0)
    out = base_to_svg(poly, tmp_path / "heart.svg", 75.0)
    assert out.exists()
    assert out.stat().st_size > 100


def test_base_to_svg_contains_path_element(tmp_path):
    poly = get_base("circle", 75.0)
    out = base_to_svg(poly, tmp_path / "circle.svg", 75.0)
    content = out.read_text()
    assert '<path' in content
    assert 'fill="black"' in content


def test_base_to_svg_has_mm_units(tmp_path):
    poly = get_base("rectangle", 75.0)
    out = base_to_svg(poly, tmp_path / "rect.svg", 75.0)
    content = out.read_text()
    assert "mm" in content


@pytest.mark.parametrize("name", TIER1)
def test_base_to_svg_all_tier1(tmp_path, name):
    """Wszystkie Tier 1 shapes zapisują się jako poprawny SVG."""
    poly = get_base(name, 75.0)
    out = base_to_svg(poly, tmp_path / f"{name}.svg", 75.0)
    assert out.exists() and out.stat().st_size > 50


# ── scad_export ───────────────────────────────────────────────────────────────

def test_poly_points_format():
    """_poly_points zwraca string z listą [x,y] par."""
    poly = get_base("circle", 10.0)
    pts = _poly_points(poly)
    assert pts.startswith("[")
    assert pts.endswith("]")
    assert "[" in pts and "," in pts


def test_cutter_scad_contains_module(tmp_path):
    poly = get_base("heart", 75.0)
    scad = cutter_scad(poly, 75.0)
    assert "module base()" in scad
    assert "polygon(points=" in scad
    assert "difference()" in scad
    assert "linear_extrude" in scad


def test_cutter_scad_mentions_size(tmp_path):
    poly = get_base("circle", 90.0)
    scad = cutter_scad(poly, 90.0)
    assert "90.0" in scad


def test_stamp_scad_contains_both_modules(tmp_path):
    base = get_base("heart", 75.0)
    stamp = get_base("circle", 40.0)
    scad = stamp_scad(base, stamp, 75.0)
    assert "module base()" in scad
    assert "module stamp_pattern()" in scad
    assert "stamp_pattern()" in scad


def test_cutter_scad_has_fn_param():
    """$fn powinien być ustawiony dla gładkości okręgów w offset()."""
    poly = get_base("circle", 75.0)
    scad = cutter_scad(poly, 75.0)
    assert "$fn=" in scad


@pytest.mark.parametrize("name", TIER1)
def test_cutter_scad_all_tier1(name):
    """Wszystkie Tier 1 shapes generują niepusty SCAD dla cuttera."""
    poly = get_base(name, 75.0)
    scad = cutter_scad(poly, 75.0)
    assert len(scad) > 200
    assert "polygon(points=" in scad
