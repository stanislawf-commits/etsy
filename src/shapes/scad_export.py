"""
src/shapes/scad_export.py — generuje OpenSCAD (.scad) dla cutterów i stempli (Typ B).

Publiczne API:
    cutter_scad(base_poly, size_mm) -> str
    stamp_scad(base_poly, stamp_poly, size_mm) -> str
    run_openscad(scad_str, output_stl, timeout) -> bool
"""

import subprocess
import tempfile
from pathlib import Path

from shapely.geometry import Polygon

from src.utils.config_loader import cfg


def _stl_cfg() -> dict:
    return cfg("base_shapes").get("stl_defaults", {})


def _poly_points(poly: Polygon) -> str:
    """Konwertuje exterior do OpenSCAD points=[...]."""
    coords = list(poly.exterior.coords)[:-1]  # usuń zamykający duplikat
    return "[" + ", ".join(f"[{x:.4f},{y:.4f}]" for x, y in coords) + "]"


def _poly_module(poly: Polygon, name: str) -> str:
    """Generuje moduł OpenSCAD: module <name>() { polygon(...); }"""
    return f"module {name}() {{ polygon(points={_poly_points(poly)}); }}"


def cutter_scad(base_poly: Polygon, size_mm: float) -> str:
    """
    Generuje kod OpenSCAD dla cuttera Typ B.

    Struktura:
      - outer shell: base_poly offset(+wall_thick) na pełną wysokość
      - hollow:      base_poly offset(-cutting_edge) od base_thick w górę
      - bottom base: base_poly offset(+wall_thick) na base_thick
    """
    c = _stl_cfg()
    wall   = c.get("wall_thick_mm",   1.8)
    total  = c.get("total_height_mm", 12.0)
    base_h = c.get("base_thick_mm",   3.0)
    blade  = c.get("cutting_edge_mm", 0.4)
    fn     = c.get("fn",              128)

    return (
        f"$fn={fn};\n"
        f"{_poly_module(base_poly, 'base')}\n\n"
        f"// Cutter Typ B — {size_mm:.1f}mm\n"
        f"// outer wall\n"
        f"difference() {{\n"
        f"  linear_extrude(height={total})\n"
        f"    offset(r={wall}, $fn={fn}) base();\n"
        f"  // hollow — od base_thick w górę, ostrze -{blade}mm\n"
        f"  translate([0, 0, {base_h}])\n"
        f"  linear_extrude(height={total - base_h + 0.1})\n"
        f"    offset(r=-{blade}, $fn={fn}) base();\n"
        f"}}\n"
        f"// dno\n"
        f"linear_extrude(height={base_h})\n"
        f"  offset(r={wall}, $fn={fn}) base();\n"
    )


def stamp_scad(base_poly: Polygon, stamp_poly: Polygon, size_mm: float) -> str:
    """
    Generuje OpenSCAD dla stempla Typ B.

    base_poly  — kształt bazy (dopasowany do cuttera)
    stamp_poly — wzór stempla (generowany przez Claude / stamp_elements)
    """
    c = _stl_cfg()
    base_h = c.get("base_thick_mm",   3.0)
    relief = c.get("relief_height_mm", 2.0)
    wall   = c.get("wall_thick_mm",    1.8)
    fn     = c.get("fn",               128)

    return (
        f"$fn={fn};\n"
        f"{_poly_module(base_poly,   'base')}\n"
        f"{_poly_module(stamp_poly,  'stamp_pattern')}\n\n"
        f"// Stamp Typ B — {size_mm:.1f}mm\n"
        f"// podstawa\n"
        f"linear_extrude(height={base_h})\n"
        f"  offset(r={wall}, $fn={fn}) base();\n"
        f"// relief\n"
        f"translate([0, 0, {base_h}])\n"
        f"linear_extrude(height={relief})\n"
        f"  stamp_pattern();\n"
    )


def run_openscad(scad_str: str, output_stl: Path, timeout: int = 120) -> bool:
    """
    Uruchamia OpenSCAD CLI i zapisuje STL.
    Zwraca True gdy plik STL wygenerowany poprawnie.
    """
    output_stl = Path(output_stl)
    output_stl.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        suffix=".scad", mode="w", delete=False, encoding="utf-8"
    ) as f:
        f.write(scad_str)
        scad_path = f.name

    try:
        r = subprocess.run(
            ["openscad", "--export-format", "binstl", "-o", str(output_stl), scad_path],
            capture_output=True,
            timeout=timeout,
        )
        return r.returncode == 0 and output_stl.exists() and output_stl.stat().st_size > 84
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    finally:
        Path(scad_path).unlink(missing_ok=True)
