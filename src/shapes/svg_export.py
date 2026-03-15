"""
src/shapes/svg_export.py — eksport Shapely Polygon do pliku SVG.

Publiczne API:
    base_to_svg(poly, path, size_mm) -> Path
    poly_to_path_d(poly) -> str
"""

from pathlib import Path

from shapely import affinity
from shapely.geometry import Polygon


def poly_to_path_d(poly: Polygon) -> str:
    """Konwertuje exterior Polygonu na atrybut 'd' ścieżki SVG."""
    coords = list(poly.exterior.coords)[:-1]  # usuń zamykający duplikat
    if not coords:
        return ""
    parts = [f"M {coords[0][0]:.4f},{coords[0][1]:.4f}"]
    for x, y in coords[1:]:
        parts.append(f"L {x:.4f},{y:.4f}")
    parts.append("Z")
    return " ".join(parts)


def base_to_svg(poly: Polygon, path: Path, size_mm: float) -> Path:
    """
    Zapisuje Shapely Polygon jako SVG.

    SVG Y oś rośnie w dół — odwracamy Shapely Y dla poprawnego renderowania.
    width/height w mm, viewBox wyrównany do bounding box.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Flip Y: SVG Y↓, Shapely Y↑
    poly_svg = affinity.scale(poly, xfact=1, yfact=-1, origin=(0, 0))

    b = poly_svg.bounds  # (minx, miny, maxx, maxy)
    vb_x, vb_y = b[0], b[1]
    vb_w, vb_h = b[2] - b[0], b[3] - b[1]

    d = poly_to_path_d(poly_svg)

    svg = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{vb_w:.4f}mm" height="{vb_h:.4f}mm"'
        f' viewBox="{vb_x:.4f} {vb_y:.4f} {vb_w:.4f} {vb_h:.4f}">\n'
        f'  <path d="{d}" fill="black" stroke="none"/>\n'
        f'</svg>\n'
    )
    path.write_text(svg, encoding="utf-8")
    return path
