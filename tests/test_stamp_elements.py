"""
test_stamp_elements.py — testy src/shapes/stamp_elements.py.

Pokrywa:
  - mock_plan(): poprawna struktura, liczba elementów
  - build_relief(): valid Polygon, przycięty do bazy
  - _build_element(): wszystkie typy, rotacja, pozycja
  - plan_stamp(): mock Claude → plan → relief end-to-end
  - Integracja: mock_plan → build_relief → generate_stamp_stl (STL file)
"""
import math
from pathlib import Path
from unittest.mock import patch

import pytest
from shapely.geometry import Polygon

from src.shapes.stamp_elements import (
    mock_plan,
    build_relief,
    plan_stamp,
    ELEMENT_TYPES,
    _build_element,
    _shape_by_type,
)
from src.shapes.base_shapes import get_base


# ── mock_plan ─────────────────────────────────────────────────────────────────

def test_mock_plan_returns_dict():
    plan = mock_plan("flowers", 75.0)
    assert isinstance(plan, dict)
    assert "elements" in plan
    assert "topic" in plan
    assert "size_mm" in plan


def test_mock_plan_elements_have_required_fields():
    plan = mock_plan("stars", 60.0)
    for el in plan["elements"]:
        assert "type" in el
        assert "x" in el
        assert "y" in el
        assert "size" in el
        assert el["size"] >= 1.0


def test_mock_plan_n_elements():
    plan = mock_plan("leaf", 75.0, n=5)
    assert len(plan["elements"]) >= 4  # co najmniej n-1

    plan2 = mock_plan("floral", 75.0, n=9)
    assert len(plan2["elements"]) >= 7


def test_mock_plan_elements_within_base():
    """Elementy mock_plan powinny mieścić się w obszarze bazy (±0.8 * size_mm/2)."""
    size_mm = 75.0
    plan = mock_plan("generic", size_mm)
    limit = size_mm * 0.8
    for el in plan["elements"]:
        dist = math.hypot(el["x"], el["y"])
        assert dist < limit, f"Element {el['type']} za daleko od centrum: dist={dist:.1f}"


# ── build_relief ─────────────────────────────────────────────────────────────

def test_build_relief_returns_polygon():
    plan = mock_plan("flowers", 75.0)
    relief = build_relief(plan)
    assert isinstance(relief, Polygon)
    assert relief.is_valid
    assert not relief.is_empty


def test_build_relief_clipped_to_base():
    """Relief przycięty do bazy musi być podzbiorem bazy (z małym marginesem)."""
    base = get_base("heart", 75.0)
    plan = mock_plan("daisy", 75.0)
    relief = build_relief(plan, base_poly=base)
    # relief powinien być wewnątrz base (z tolerancją 0.5mm)
    assert base.buffer(0.5).contains(relief)


def test_build_relief_all_tier1_bases():
    """build_relief działa poprawnie dla każdego Tier 1 kształtu bazy."""
    tier1 = ["heart", "circle", "rectangle", "squircle", "star5", "arch", "oval", "cloud"]
    for name in tier1:
        base = get_base(name, 75.0)
        plan = mock_plan("flowers", 75.0)
        relief = build_relief(plan, base_poly=base)
        assert isinstance(relief, Polygon), f"{name}: nie Polygon"
        assert relief.is_valid, f"{name}: invalid"
        assert not relief.is_empty, f"{name}: empty"


def test_build_relief_empty_elements_returns_fallback():
    """Pusty elements → fallback circle."""
    plan = {"topic": "test", "size_mm": 75.0, "elements": []}
    relief = build_relief(plan)
    assert isinstance(relief, Polygon)
    assert relief.area > 0


def test_build_relief_area_nonzero():
    plan = mock_plan("test", 75.0)
    relief = build_relief(plan)
    assert relief.area > 10.0


# ── _build_element + _shape_by_type ──────────────────────────────────────────

@pytest.mark.parametrize("el_type", ELEMENT_TYPES)
def test_all_element_types_valid(el_type):
    """Każdy typ elementu zwraca valid Polygon."""
    el = {"type": el_type, "x": 0.0, "y": 0.0, "size": 10.0, "rotation": 0}
    shape = _build_element(el)
    assert shape is not None
    assert isinstance(shape, Polygon)
    assert shape.is_valid
    assert shape.area > 0


@pytest.mark.parametrize("el_type", ELEMENT_TYPES)
def test_element_rotation_applied(el_type):
    """Rotacja 45° zmienia geometrię (z wyjątkiem circle/dot które są symetryczne)."""
    el0 = {"type": el_type, "x": 0, "y": 0, "size": 12.0, "rotation": 0}
    el1 = {"type": el_type, "x": 0, "y": 0, "size": 12.0, "rotation": 45}
    s0 = _build_element(el0)
    s1 = _build_element(el1)
    if el_type in ("circle", "dot", "ring"):
        # Kształty radialnie symetryczne — bounding box taki sam po rotacji
        assert abs(s0.area - s1.area) < 0.5
    else:
        # Inne kształty — bounding box powinien się zmienić
        b0 = s0.bounds
        b1 = s1.bounds
        changed = any(abs(b0[i] - b1[i]) > 0.01 for i in range(4))
        assert changed, f"{el_type}: rotacja nie zmieniła kształtu"


def test_element_position_applied():
    """Pozycja x,y przesuwa element."""
    el0 = {"type": "circle", "x": 0.0,  "y": 0.0,  "size": 5.0, "rotation": 0}
    el1 = {"type": "circle", "x": 20.0, "y": 15.0, "size": 5.0, "rotation": 0}
    s0 = _build_element(el0)
    s1 = _build_element(el1)
    cx0 = (s0.bounds[0] + s0.bounds[2]) / 2
    cx1 = (s1.bounds[0] + s1.bounds[2]) / 2
    cy0 = (s0.bounds[1] + s0.bounds[3]) / 2
    cy1 = (s1.bounds[1] + s1.bounds[3]) / 2
    assert abs(cx1 - cx0 - 20.0) < 0.1
    assert abs(cy1 - cy0 - 15.0) < 0.1


def test_element_minimum_size():
    """Elementy < 1mm są clampowane do 1mm."""
    el = {"type": "circle", "x": 0, "y": 0, "size": 0.1, "rotation": 0}
    shape = _build_element(el)
    assert shape is not None
    assert shape.area > 0


# ── plan_stamp (z mock Claude API) ───────────────────────────────────────────

_MOCK_CLAUDE_PLAN = {
    "elements": [
        {"type": "circle",    "x":  0.0, "y":  0.0,  "size": 15.0, "rotation": 0},
        {"type": "petal",     "x": 20.0, "y":  0.0,  "size": 10.0, "rotation": 90},
        {"type": "petal",     "x": -20.0, "y": 0.0,  "size": 10.0, "rotation": 270},
        {"type": "leaf",      "x":  0.0, "y": 20.0,  "size": 8.0,  "rotation": 0},
        {"type": "star5",     "x":  0.0, "y": -20.0, "size": 8.0,  "rotation": 0},
    ]
}


def test_plan_stamp_uses_claude_json():
    """plan_stamp() wywołuje claude_json i zwraca plan z elements."""
    from src.shapes import stamp_elements
    product = {"stamp_topic": "floral wreath", "base_shape": "heart", "size_mm": 75.0}
    with patch.object(stamp_elements, "claude_json", return_value=_MOCK_CLAUDE_PLAN) as mock_cj:
        plan = stamp_elements.plan_stamp(product)
    mock_cj.assert_called_once()
    assert "elements" in plan
    assert len(plan["elements"]) == 5


def test_plan_stamp_fallback_on_error():
    """plan_stamp() wraca do mock_plan() gdy Claude API rzuci wyjątek."""
    from src.shapes import stamp_elements
    product = {"stamp_topic": "stars", "base_shape": "circle", "size_mm": 60.0}
    with patch.object(stamp_elements, "claude_json", side_effect=RuntimeError("API error")):
        plan = stamp_elements.plan_stamp(product)
    assert "elements" in plan
    assert len(plan["elements"]) >= 1  # fallback mock_plan


def test_plan_stamp_sets_meta_fields():
    """plan_stamp() ustawia topic, base_shape, size_mm w planie."""
    from src.shapes import stamp_elements
    product = {"stamp_topic": "daisies", "base_shape": "circle", "size_mm": 90.0}
    with patch.object(stamp_elements, "claude_json", return_value=_MOCK_CLAUDE_PLAN):
        plan = stamp_elements.plan_stamp(product)
    assert plan.get("topic") == "daisies"
    assert plan.get("base_shape") == "circle"
    assert plan.get("size_mm") == 90.0


# ── Integracja: mock_plan → build_relief → STL ───────────────────────────────

def test_stamp_relief_to_stl(tmp_path):
    """mock_plan → build_relief → generate_stamp_stl → valid STL plik."""
    from src.agents.model_agent import PurePythonSTLWriter, STLValidator

    base  = get_base("heart", 75.0)
    plan  = mock_plan("floral wreath", 75.0, n=9)
    relief = build_relief(plan, base_poly=base)

    contour   = list(relief.exterior.coords)[:-1]
    cfg       = {
        "total_height": 12.0, "base_thick": 4.0,
        "wall_thick": 1.8, "cutting_edge": 0.4,
        "relief_height": 2.0, "taper_height": 3.0,
    }
    stl_path  = tmp_path / "stamp_test.stl"
    writer    = PurePythonSTLWriter()
    n_tri     = writer.generate_stamp_stl(contour, cfg, stl_path)

    assert stl_path.exists()
    assert stl_path.stat().st_size > 84
    assert n_tri > 0

    result = STLValidator().validate(stl_path, cfg)
    assert result["valid"] is True


def test_stamp_model_agent_generate_type_b(tmp_path):
    """model_agent.generate_type_b() z stamp + stamp_poly → valid STL."""
    from src.agents.model_agent import create_model_agent

    base   = get_base("heart", 75.0)
    plan   = mock_plan("flowers", 75.0, n=7)
    relief = build_relief(plan, base_poly=base)

    agent  = create_model_agent("pure_python")
    result = agent.generate_type_b(
        base_poly=base,
        size_mm=75.0,
        product_type="stamp",
        output_dir=tmp_path,
        size_key="M",
        stamp_poly=relief,
    )
    assert result["valid"] is True, f"STL invalid: {result.get('error')}"
    assert Path(result["stl_path"]).name == "M_stamp.stl"
