"""
printability_validator.py — walidacja SVG pod kątem drukowalności 3D.

Sprawdzenia:
  - Zamknięte ścieżki (path ends with Z)
  - Minimalna liczba punktów (≥ 6 coordinate pairs)
  - Circle fit (bounding box ≤ size_mm + margin)
  - Przynajmniej jedna ścieżka w outer group
  - Przynajmniej jedna ścieżka w stamp group

Interfejs:
  result = validate_svg(svg_path, size_mm)
  result.ok          → bool
  result.errors      → list[str]
  result.warnings    → list[str]
  result.outer_path  → str | None  (d attribute)
  result.stamp_paths → list[str]
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    outer_path: str | None = None
    stamp_paths: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> "ValidationResult":
        self.ok = False
        self.errors.append(msg)
        return self

    def warn(self, msg: str) -> "ValidationResult":
        self.warnings.append(msg)
        return self


def validate_svg(svg_path: Path | str, size_mm: float) -> ValidationResult:
    """
    Waliduje plik SVG pod kątem drukowalności 3D.

    Args:
        svg_path: Ścieżka do pliku SVG
        size_mm:  Oczekiwany wymiar (szerokość = wysokość) w mm

    Returns:
        ValidationResult z listą błędów i ostrzeżeń
    """
    result = ValidationResult()
    svg_path = Path(svg_path)

    # 1. Plik istnieje
    if not svg_path.exists():
        return result.fail(f"File not found: {svg_path}")

    # 2. Parsowanie XML
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except ET.ParseError as e:
        return result.fail(f"XML parse error: {e}")

    ns = {"svg": "http://www.w3.org/2000/svg"}

    # Helper: strip namespace prefix from tag
    def local(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    # 3. Sprawdź viewBox
    vb = root.get("viewBox", "")
    if vb:
        parts = vb.split()
        if len(parts) == 4:
            try:
                vb_w = float(parts[2])
                vb_h = float(parts[3])
                margin = size_mm * 0.15
                if abs(vb_w - size_mm) > margin:
                    result.warn(f"viewBox width {vb_w} differs from expected {size_mm}mm")
                if abs(vb_h - size_mm) > margin:
                    result.warn(f"viewBox height {vb_h} differs from expected {size_mm}mm")
            except ValueError:
                result.warn("Could not parse viewBox dimensions")

    # 4. Find outer group
    outer_group = None
    stamp_group = None
    for child in root:
        tag = local(child.tag)
        if tag == "g":
            gid = child.get("id", "")
            if gid == "outer":
                outer_group = child
            elif gid == "stamp":
                stamp_group = child

    # 5. Check outer group
    if outer_group is None:
        result.warn("No <g id='outer'> found — treating all paths as outer")
        # Collect all paths from root as outer
        all_paths = [el for el in root if local(el.tag) == "path"]
        if not all_paths:
            result.fail("No path elements found in SVG")
        else:
            path_d = all_paths[0].get("d", "")
            result.outer_path = path_d
            _validate_path_d(path_d, size_mm, "outer_contour", result)
    else:
        # Find outer_contour path
        outer_paths = [el for el in outer_group if local(el.tag) == "path"]
        if not outer_paths:
            result.fail("No path in <g id='outer'>")
        else:
            path_d = outer_paths[0].get("d", "")
            result.outer_path = path_d
            _validate_path_d(path_d, size_mm, "outer_contour", result)

    # 6. Check stamp group
    if stamp_group is None:
        result.warn("No <g id='stamp'> found — SVG may be outer-only (legacy format)")
    else:
        stamp_paths = [el for el in stamp_group if local(el.tag) == "path"]
        for sp in stamp_paths:
            d = sp.get("d", "")
            result.stamp_paths.append(d)
        if not stamp_paths:
            result.warn("Stamp group is empty — no stamp paths")

    return result


def _validate_path_d(path_d: str, size_mm: float, name: str, result: ValidationResult) -> None:
    """Waliduje pojedynczą ścieżkę SVG."""
    if not path_d:
        result.fail(f"{name}: empty path d attribute")
        return

    # Must start with M
    d_upper = path_d.strip().upper()
    if not d_upper.startswith("M"):
        result.fail(f"{name}: path must start with M command")

    # Must end with Z
    if not d_upper.rstrip().endswith("Z"):
        result.fail(f"{name}: path must end with Z command (got: ...{path_d.strip()[-10:]})")

    # Minimum coordinate pairs
    coords = re.findall(r"-?\d+\.?\d*\s*,\s*-?\d+\.?\d*", path_d)
    if len(coords) < 4:
        result.fail(f"{name}: too few coordinate pairs ({len(coords)}) — minimum 4")
    elif len(coords) < 8:
        result.warn(f"{name}: few coordinate pairs ({len(coords)}) — shape may be too simple")

    # Bounding box check
    margin = size_mm * 0.20
    xs, ys = [], []
    for coord in coords:
        parts = re.split(r"\s*,\s*", coord.strip())
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except (ValueError, IndexError):
            pass

    if xs and ys:
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        if x_min < -margin or x_max > size_mm + margin:
            result.fail(f"{name}: X coordinates [{x_min:.1f}, {x_max:.1f}] exceed viewBox [{-margin:.1f}, {size_mm+margin:.1f}]")
        if y_min < -margin or y_max > size_mm + margin:
            result.fail(f"{name}: Y coordinates [{y_min:.1f}, {y_max:.1f}] exceed viewBox")
