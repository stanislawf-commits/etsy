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
    # S2.5 new shapes
    _path_cat,
    _path_dog,
    _path_rabbit,
    _path_bear,
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
        sizes=["M", "XXXXL"],
        output_dir=tmp_path,
    )
    assert result["success"]  # M succeeded
    assert len(result["files"]) == 1
    assert "errors" in result
    assert any("XXXXL" in e for e in result["errors"])


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
    """Stamp product_type musi generować SVG z outer i stamp group."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="heart",
        product_type="stamp",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert result["success"]
    svg_content = Path(result["files"][0]["path"]).read_text()
    assert '<g id="outer">' in svg_content
    assert '<g id="stamp">' in svg_content


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


# ── S2.6: SIZE_MM includes XXXL ──────────────────────────────────────────────

def test_size_mm_contains_xxxl():
    assert "XXXL" in SIZE_MM
    assert SIZE_MM["XXXL"] == 150.0


def test_size_mm_has_all_sizes():
    for key in ("XS", "S", "M", "L", "XL", "XXXL"):
        assert key in SIZE_MM, f"SIZE_MM missing key: {key}"


def test_xxxl_size_generation(tmp_path):
    """XXXL rozmiar musi generować plik SVG bez błędów."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="star",
        product_type="cutter",
        sizes=["XXXL"],
        output_dir=tmp_path,
    )
    assert result["success"]
    assert len(result["files"]) == 1
    assert result["files"][0]["width_mm"] == SIZE_MM["XXXL"]


# ── S2.5: new shape detectors ─────────────────────────────────────────────────

def test_detect_cat():
    assert _detect_shape("cat cutter") == "cat"
    assert _detect_shape("kitten cookie") == "cat"
    assert _detect_shape("kitty shape") == "cat"


def test_detect_dog():
    assert _detect_shape("dog cutter") == "dog"
    assert _detect_shape("puppy cookie") == "dog"
    assert _detect_shape("dachshund shape") == "dog"


def test_detect_rabbit():
    assert _detect_shape("rabbit cutter") == "rabbit"
    assert _detect_shape("bunny cookie") == "rabbit"
    assert _detect_shape("hare shape") == "rabbit"


def test_detect_hen():
    assert _detect_shape("hen cutter") == "hen"
    assert _detect_shape("chicken cookie") == "hen"
    assert _detect_shape("chick shape") == "hen"


def test_detect_bear():
    assert _detect_shape("bear cutter") == "bear"
    assert _detect_shape("teddy cookie") == "bear"


def test_detect_owl():
    assert _detect_shape("owl cutter") == "owl"


def test_detect_llama():
    assert _detect_shape("llama cutter") == "llama"
    assert _detect_shape("alpaca cookie") == "llama"


def test_detect_fish():
    assert _detect_shape("fish cutter") == "fish"
    assert _detect_shape("goldfish cookie") == "fish"


def test_detect_bird():
    assert _detect_shape("bird cutter") == "bird"
    assert _detect_shape("robin cookie") == "bird"


def test_detect_apple():
    assert _detect_shape("apple cutter") == "apple"


def test_detect_cactus():
    assert _detect_shape("cactus cutter") == "cactus"
    assert _detect_shape("succulent shape") == "cactus"


def test_detect_strawberry():
    assert _detect_shape("strawberry cutter") == "strawberry"


def test_detect_tulip():
    assert _detect_shape("tulip cutter") == "tulip"


def test_detect_easter_egg():
    assert _detect_shape("easter cutter") == "easter_egg"
    assert _detect_shape("egg cookie") == "easter_egg"


def test_detect_crown():
    assert _detect_shape("crown cutter") == "crown"
    assert _detect_shape("princess cookie") == "crown"
    assert _detect_shape("queen shape") == "crown"


def test_detect_cookie():
    assert _detect_shape("cookie cutter") == "cookie"
    assert _detect_shape("biscuit shape") == "cookie"


# ── S2.5: new shape functions (path structure) ────────────────────────────────

@pytest.mark.parametrize("shape_fn,args", [
    (_path_cat, (37.5, 37.5, 17.25)),
    (_path_dog, (37.5, 37.5, 17.25)),
    (_path_rabbit, (37.5, 37.5, 17.25)),
    (_path_bear, (37.5, 37.5, 17.25)),
])
def test_new_shape_starts_M_ends_Z(shape_fn, args):
    path_d = shape_fn(*args)
    d_upper = path_d.strip().upper()
    assert d_upper.startswith("M"), f"{shape_fn.__name__}: doesn't start with M"
    assert d_upper.rstrip().endswith("Z"), f"{shape_fn.__name__}: doesn't end with Z"


# ── S2.2: compound SVG format (outer + stamp groups) ─────────────────────────

def test_mock_svg_has_outer_group(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="cat",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    svg_path = Path(result["files"][0]["path"])
    content = svg_path.read_text()
    assert '<g id="outer">' in content, "SVG must have <g id='outer'> group"


def test_mock_svg_has_stamp_group(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="cat",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    svg_path = Path(result["files"][0]["path"])
    content = svg_path.read_text()
    assert '<g id="stamp">' in content, "SVG must have <g id='stamp'> group"


def test_mock_svg_has_outer_contour_path(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="bear",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    svg_path = Path(result["files"][0]["path"])
    content = svg_path.read_text()
    assert 'id="outer_contour"' in content


def test_mock_svg_has_stamp_outline(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="rabbit",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    svg_path = Path(result["files"][0]["path"])
    content = svg_path.read_text()
    assert 'id="stamp_outline"' in content


def test_creature_mock_has_eyes(tmp_path):
    """Creature shapes should have eye elements in stamp group."""
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="cat",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    svg_path = Path(result["files"][0]["path"])
    content = svg_path.read_text()
    assert 'id="eye_l"' in content
    assert 'id="eye_r"' in content


def test_result_has_has_stamp_field(tmp_path):
    agent = create_design_agent("mock")
    result = agent.generate(
        topic="dog",
        product_type="cutter",
        sizes=["M"],
        output_dir=tmp_path,
    )
    assert "has_stamp" in result["files"][0]
    assert result["files"][0]["has_stamp"] is True


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
