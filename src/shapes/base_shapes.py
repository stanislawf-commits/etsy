"""
src/shapes/base_shapes.py — standardowe bazy (Tier 1) jako Shapely Polygon.

Publiczne API:
    get_base(name: str, size_mm: float) -> shapely.geometry.Polygon
    list_bases(tier: int | None = None) -> list[str]

Centrum w (0, 0). size_mm = najdłuższy wymiar bounding box.
"""

import math

from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union

from src.utils.config_loader import cfg

_FN = 128  # quad_segs dla Point.buffer — jakość okręgów


def list_bases(tier: int | None = None) -> list[str]:
    """Zwraca listę dostępnych baz (opcjonalnie filtruje po tier)."""
    shapes = cfg("base_shapes").get("base_shapes", {})
    if tier is None:
        return list(shapes.keys())
    return [k for k, v in shapes.items() if v.get("tier") == tier]


def get_base(name: str, size_mm: float) -> Polygon:
    """
    Zwraca Shapely Polygon dla podanej bazy, skalowany do size_mm.
    Centrum w (0, 0). Bounding box max dim ≈ size_mm.
    """
    builders = {
        "heart":     _heart,
        "circle":    _circle,
        "rectangle": _rectangle,
        "squircle":  _squircle,
        "star5":     _star5,
        "arch":      _arch,
        "oval":      _oval,
        "cloud":     _cloud,
    }
    if name not in builders:
        raise ValueError(
            f"Shape {name!r} not implemented. Tier 1: {list(builders)}"
        )
    return builders[name](size_mm)


def _scale_center(poly: Polygon, size_mm: float) -> Polygon:
    """Skaluje polygon do size_mm (max dim bounding box) i centruje na (0,0)."""
    b = poly.bounds  # (minx, miny, maxx, maxy)
    span = max(b[2] - b[0], b[3] - b[1])
    if span < 1e-9:
        return poly
    sc = size_mm / span
    poly = affinity.scale(poly, xfact=sc, yfact=sc, origin=(0, 0))
    cx = (poly.bounds[0] + poly.bounds[2]) / 2
    cy = (poly.bounds[1] + poly.bounds[3]) / 2
    return affinity.translate(poly, -cx, -cy)


# ── Tier 1 builders ────────────────────────────────────────────────────────────

def _heart(size_mm: float) -> Polygon:
    """Serce — klasyczna krzywa parametryczna."""
    pts = []
    for i in range(_FN):
        t = 2 * math.pi * i / _FN
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x, -y))  # -y: serce skierowane czubkiem w górę
    return _scale_center(Polygon(pts), size_mm)


def _circle(size_mm: float) -> Polygon:
    """Koło."""
    return Point(0, 0).buffer(size_mm / 2, quad_segs=_FN // 4)


def _rectangle(size_mm: float) -> Polygon:
    """Prostokąt z zaokrąglonymi rogami (aspect 1.4:1, corner r=6%)."""
    w = size_mm
    h = size_mm / 1.4
    r = size_mm * 0.06
    inner = shapely_box(-(w / 2 - r), -(h / 2 - r), w / 2 - r, h / 2 - r)
    return inner.buffer(r, join_style="round", quad_segs=16)


def _squircle(size_mm: float) -> Polygon:
    """Zaokrąglony kwadrat (corner r=18%)."""
    s = size_mm
    r = s * 0.18
    inner = shapely_box(-(s / 2 - r), -(s / 2 - r), s / 2 - r, s / 2 - r)
    return inner.buffer(r, join_style="round", quad_segs=32)


def _star5(size_mm: float) -> Polygon:
    """Gwiazda 5-ramienna z lekko zaokrąglonymi czubkami."""
    n = 5
    r_outer = size_mm / 2
    r_inner = r_outer * 0.42
    pts = []
    for i in range(n * 2):
        angle = math.pi * i / n - math.pi / 2  # czubek na górze
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((r * math.cos(angle), r * math.sin(angle)))
    star = Polygon(pts)
    r_tip = size_mm * 0.03
    # zaokrąglenie czubków: dilate + erode
    rounded = star.buffer(r_tip, join_style="round", quad_segs=8).buffer(
        -r_tip, join_style="round", quad_segs=8
    )
    return _scale_center(rounded, size_mm)


def _arch(size_mm: float) -> Polygon:
    """Łuk — górne rogi jako półkole, dół płaski (aspect 0.75, portret)."""
    w = size_mm * 0.75
    h = size_mm
    r = w / 2  # promień półkola = pół szerokości
    rect = shapely_box(-w / 2, -h / 2, w / 2, h / 2 - r)
    top = Point(0, h / 2 - r).buffer(r, quad_segs=32)
    return _scale_center(rect.union(top), size_mm)


def _oval(size_mm: float) -> Polygon:
    """Owal — aspect_ratio 0.72 (portret, rx < ry)."""
    ry = size_mm / 2
    rx = ry * 0.72
    circle = Point(0, 0).buffer(ry, quad_segs=_FN // 4)
    return affinity.scale(circle, xfact=rx / ry, yfact=1.0)


def _cloud(size_mm: float) -> Polygon:
    """Chmurka — zbiór nakładających się kół (aspect_ratio ~1.6, szeroka)."""
    # Projektujemy w przestrzeni jednostkowej, potem skalujemy
    # Cel: 5 "garbów" ułożonych w charakterystyczny kształt chmurki
    r_c = 1.0   # centrum (największy)
    r_s = 0.75  # boczne środkowe
    r_b = 0.55  # boczne zewnętrzne
    circles = [
        Point(0.0,   0.55).buffer(r_c, quad_segs=32),   # centrum — wysoko
        Point(-0.90, 0.25).buffer(r_s, quad_segs=24),   # lewy środek
        Point( 0.90, 0.25).buffer(r_s, quad_segs=24),   # prawy środek
        Point(-1.65, -0.10).buffer(r_b, quad_segs=24),  # lewy bok
        Point( 1.65, -0.10).buffer(r_b, quad_segs=24),  # prawy bok
    ]
    cloud = unary_union(circles)
    # Dopasuj do target aspect ratio 1.6 (ściskamy poziomo)
    b = cloud.bounds
    actual_ar = (b[2] - b[0]) / max(b[3] - b[1], 1e-9)
    cloud = affinity.scale(cloud, xfact=1.6 / actual_ar, yfact=1.0, origin=(0, 0))
    return _scale_center(cloud, size_mm)
