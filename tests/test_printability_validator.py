"""
test_printability_validator.py — testy src/utils/printability_validator.py
"""
import tempfile
from pathlib import Path
import pytest
from src.utils.printability_validator import validate_svg, ValidationResult


def _write_temp_svg(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=".svg", mode="w", delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return Path(f.name)


VALID_COMPOUND_SVG = '''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="75mm" height="75mm" viewBox="0 0 75 75">
  <rect width="75mm" height="75mm" fill="white"/>
  <g id="outer">
    <path id="outer_contour" d="M 37.5,10 C 60,10 65,30 65,37.5 C 65,55 55,65 37.5,65 C 20,65 10,55 10,37.5 C 10,20 15,10 37.5,10 Z" fill="none" stroke="#000000" stroke-width="1.2"/>
  </g>
  <g id="stamp">
    <path id="stamp_outline" d="M 37.5,15 C 55,15 60,30 60,37.5 C 60,50 50,60 37.5,60 C 25,60 15,50 15,37.5 C 15,22 20,15 37.5,15 Z" fill="none" stroke="#666666" stroke-width="0.8"/>
    <circle id="eye_l" cx="30" cy="32" r="3" fill="#333333"/>
    <circle id="eye_r" cx="45" cy="32" r="3" fill="#333333"/>
  </g>
</svg>'''

LEGACY_SVG = '''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="75mm" height="75mm" viewBox="0 0 75 75">
  <path d="M 37.5,10 L 65,65 L 10,65 Z" fill="none" stroke="#000000"/>
</svg>'''

INVALID_NO_PATH_SVG = '''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="75mm" height="75mm" viewBox="0 0 75 75">
  <g id="outer"><rect x="10" y="10" width="55" height="55"/></g>
</svg>'''

MISSING_Z_SVG = '''<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="75mm" height="75mm" viewBox="0 0 75 75">
  <g id="outer">
    <path id="outer_contour" d="M 10,10 L 65,10 L 65,65 L 10,65" fill="none"/>
  </g>
</svg>'''


def test_valid_compound_svg():
    path = _write_temp_svg(VALID_COMPOUND_SVG)
    result = validate_svg(path, 75.0)
    assert result.ok is True
    assert result.outer_path is not None
    assert len(result.stamp_paths) >= 1


def test_legacy_svg_ok_with_warning():
    path = _write_temp_svg(LEGACY_SVG)
    result = validate_svg(path, 75.0)
    # Should work but warn about missing groups
    assert result.outer_path is not None
    assert any("outer" in w.lower() for w in result.warnings)


def test_file_not_found():
    result = validate_svg(Path("/nonexistent/file.svg"), 75.0)
    assert result.ok is False
    assert any("not found" in e.lower() for e in result.errors)


def test_missing_z_command():
    path = _write_temp_svg(MISSING_Z_SVG)
    result = validate_svg(path, 75.0)
    assert result.ok is False
    assert any("Z" in e for e in result.errors)


def test_no_outer_path():
    path = _write_temp_svg(INVALID_NO_PATH_SVG)
    result = validate_svg(path, 75.0)
    assert result.ok is False


def test_stamp_group_warning_when_missing():
    # Legacy SVG without stamp group should get a warning
    path = _write_temp_svg(LEGACY_SVG)
    result = validate_svg(path, 75.0)
    assert any("stamp" in w.lower() for w in result.warnings)


def test_viewbox_mismatch_warning():
    svg = VALID_COMPOUND_SVG.replace('viewBox="0 0 75 75"', 'viewBox="0 0 100 100"')
    path = _write_temp_svg(svg)
    result = validate_svg(path, 75.0)
    # Should warn but not fail
    assert any("viewBox" in w or "width" in w for w in result.warnings)


def test_result_dataclass_defaults():
    r = ValidationResult()
    assert r.ok is True
    assert r.errors == []
    assert r.warnings == []
    assert r.outer_path is None
    assert r.stamp_paths == []
