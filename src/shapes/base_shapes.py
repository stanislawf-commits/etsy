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
        # Tier 1
        "heart":            _heart,
        "circle":           _circle,
        "rectangle":        _rectangle,
        "squircle":         _squircle,
        "star5":            _star5,
        "arch":             _arch,
        "oval":             _oval,
        "cloud":            _cloud,
        # Tier 2
        "scalloped_circle": _scalloped_circle,
        "wavy_square":      _wavy_square,
        "hexagon":          _hexagon,
        "octagon":          _octagon,
        "heart_wide":       _heart_wide,
        "ghost":            _ghost,
        # Tier 3
        "christmas_tree":   _christmas_tree,
        "snowflake":        _snowflake,
        "pumpkin":          _pumpkin,
        "bunny":            _bunny,
        "easter_egg":       _easter_egg,
        "bell":             _bell,
    }
    if name not in builders:
        raise ValueError(
            f"Shape {name!r} not implemented. Available: {list(builders)}"
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


# ── Tier 2 builders ────────────────────────────────────────────────────────────

def _scalloped_circle(size_mm: float) -> Polygon:
    """Koło z 12 zaokrąglonymi ząbkami (scalloped edge)."""
    n       = 12
    r_inner = 1.0
    r_bump  = 0.22
    r_base  = r_inner - r_bump * 0.35
    base  = Point(0, 0).buffer(r_base, quad_segs=32)
    bumps = [
        Point(r_inner * math.cos(2 * math.pi * i / n),
              r_inner * math.sin(2 * math.pi * i / n)).buffer(r_bump, quad_segs=16)
        for i in range(n)
    ]
    return _scale_center(unary_union([base] + bumps), size_mm)


def _wavy_square(size_mm: float) -> Polygon:
    """Kwadrat z falowanymi krawędziami (3 fale na stronę)."""
    n_waves = 3
    n_pts   = 48
    s       = 1.0
    amp     = 0.07

    def _side(x0, y0, x1, y1, ox, oy):
        return [
            (x0 + (x1 - x0) * t + ox * amp * math.sin(2 * math.pi * n_waves * t),
             y0 + (y1 - y0) * t + oy * amp * math.sin(2 * math.pi * n_waves * t))
            for t in [i / n_pts for i in range(n_pts)]
        ]

    pts = (
        _side(-s, -s,  s, -s,  0, -1) +   # bottom  (wave downward  = outward)
        _side( s, -s,  s,  s,  1,  0) +   # right   (wave rightward = outward)
        _side( s,  s, -s,  s,  0,  1) +   # top     (wave upward    = outward)
        _side(-s,  s, -s, -s, -1,  0)     # left    (wave leftward  = outward)
    )
    return _scale_center(Polygon(pts), size_mm)


def _hexagon(size_mm: float) -> Polygon:
    """Sześciokąt foremny z zaokrąglonymi rogami (flat-top)."""
    n = 6
    r = 1.0
    pts = [
        (r * math.cos(2 * math.pi * i / n + math.pi / 6),
         r * math.sin(2 * math.pi * i / n + math.pi / 6))
        for i in range(n)
    ]
    r_c = 0.06
    return _scale_center(
        Polygon(pts).buffer(r_c, join_style="round", quad_segs=8)
                    .buffer(-r_c, join_style="round", quad_segs=8),
        size_mm,
    )


def _octagon(size_mm: float) -> Polygon:
    """Ośmiokąt foremny z zaokrąglonymi rogami (flat-top)."""
    n = 8
    r = 1.0
    pts = [
        (r * math.cos(2 * math.pi * i / n + math.pi / 8),
         r * math.sin(2 * math.pi * i / n + math.pi / 8))
        for i in range(n)
    ]
    r_c = 0.05
    return _scale_center(
        Polygon(pts).buffer(r_c, join_style="round", quad_segs=8)
                    .buffer(-r_c, join_style="round", quad_segs=8),
        size_mm,
    )


def _heart_wide(size_mm: float) -> Polygon:
    """Serce szerokie — aspect ~1.3:1 (szersze niż klasyczne)."""
    pts = []
    for i in range(_FN):
        t = 2 * math.pi * i / _FN
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x * 1.3, -y))
    return _scale_center(Polygon(pts), size_mm)


def _ghost(size_mm: float) -> Polygon:
    """Duszek — zaokrąglona gora + 3 nozki na dole."""
    head = Point(0, 0.55).buffer(1.0, quad_segs=32)
    body = shapely_box(-0.88, -0.70, 0.88, 0.55)
    main = head.union(body)
    # Wytnij 2 zaokraglone szczeliny -> 3 nozki
    gap_r = 0.26
    bot   = main.bounds[1]
    gaps  = [
        Point(-0.45, bot + gap_r * 0.70).buffer(gap_r, quad_segs=16),
        Point( 0.45, bot + gap_r * 0.70).buffer(gap_r, quad_segs=16),
    ]
    return _scale_center(main.difference(unary_union(gaps)), size_mm)


# ── Tier 3 builders ────────────────────────────────────────────────────────────

def _christmas_tree(size_mm: float) -> Polygon:
    """Choinka — 3 warstwowe trojkaty + pien."""
    layers = [
        # (half_width, y_bottom, y_top)
        (0.42, 0.28, 1.00),   # wierzcholek
        (0.65, -0.18, 0.55),  # srodek
        (0.90, -0.65, 0.08),  # dol
    ]
    polys = [Polygon([(-hw, yb), (hw, yb), (0, yt)]) for hw, yb, yt in layers]
    trunk = shapely_box(-0.13, -0.95, 0.13, -0.65)
    tree  = unary_union(polys + [trunk])
    return _scale_center(
        tree.buffer(0.04, join_style="round", quad_segs=8), size_mm
    )


def _snowflake(size_mm: float) -> Polygon:
    """Platek sniegu — 6 ramion + skosne odgalezienia."""
    arm_w     = 0.13
    arm_len   = 1.0
    br_offset = arm_len * 0.55
    br_len    = 0.28
    n         = 6

    pieces = []
    for i in range(n):
        deg = i * 60.0
        arm = Polygon([
            (-arm_w / 2, 0), (arm_w / 2, 0),
            (arm_w / 2, arm_len), (-arm_w / 2, arm_len),
        ])
        pieces.append(affinity.rotate(arm, deg, origin=(0, 0)))
        for sign in (-1, 1):
            br = Polygon([
                (-arm_w * 0.35, 0), (arm_w * 0.35, 0),
                (sign * br_len * 0.8 + arm_w * 0.35, br_len),
                (sign * br_len * 0.8 - arm_w * 0.35, br_len),
            ])
            br = affinity.translate(br, 0, br_offset)
            pieces.append(affinity.rotate(br, deg, origin=(0, 0)))

    center = Point(0, 0).buffer(arm_w * 1.5, quad_segs=12)
    return _scale_center(unary_union(pieces + [center]), size_mm)


def _pumpkin(size_mm: float) -> Polygon:
    """Dynia — 5 pionowych platow + lodygka."""
    lobe_rx   = 0.28
    lobe_ry   = 0.60
    positions = [-0.88, -0.44, 0.0, 0.44, 0.88]
    unit      = Point(0, 0).buffer(1.0, quad_segs=32)
    lobes = [
        affinity.translate(
            affinity.scale(unit, xfact=lobe_rx, yfact=lobe_ry, origin=(0, 0)),
            xoff=xp,
        )
        for xp in positions
    ]
    body  = unary_union(lobes)
    stem  = shapely_box(-0.09, body.bounds[3] - 0.04, 0.09, body.bounds[3] + 0.30)
    return _scale_center(body.union(stem), size_mm)


def _bunny(size_mm: float) -> Polygon:
    """Krolik — cialo + glowa + 2 uszy."""
    unit  = Point(0, 0).buffer(1.0, quad_segs=32)
    body  = affinity.translate(affinity.scale(unit, xfact=0.80, yfact=0.65, origin=(0, 0)), yoff=-0.45)
    head  = affinity.translate(affinity.scale(unit, xfact=0.55, yfact=0.50, origin=(0, 0)), yoff=0.25)
    ear_l = affinity.translate(affinity.scale(unit, xfact=0.20, yfact=0.55, origin=(0, 0)), xoff=-0.28, yoff=1.05)
    ear_r = affinity.translate(affinity.scale(unit, xfact=0.20, yfact=0.55, origin=(0, 0)), xoff= 0.28, yoff=1.05)
    return _scale_center(unary_union([body, head, ear_l, ear_r]), size_mm)


def _easter_egg(size_mm: float) -> Polygon:
    """Pisanka — jajko (owal szerszy u dolu, wezszy u gory)."""
    pts = []
    for i in range(_FN):
        t = 2 * math.pi * i / _FN
        x = 0.72 * math.sin(t)
        y = math.cos(t) + 0.18 * math.cos(2 * t)
        pts.append((x, y))
    return _scale_center(Polygon(pts), size_mm)


def _bell(size_mm: float) -> Polygon:
    """Dzwonek — trapez z lukiem u dolu + uchwyt."""
    w_top  = 0.30
    w_bot  = 1.00
    h_body = 0.80
    n_arc  = 32

    pts = [(-w_top, h_body), (w_top, h_body), (w_bot, 0.0)]
    for i in range(1, n_arc):
        angle = math.pi * i / n_arc
        pts.append((
            w_bot * math.cos(angle),
            -w_bot * math.sin(angle) * 0.38,
        ))
    pts.append((-w_bot, 0.0))
    bell_body = Polygon(pts).buffer(0.05, join_style="round", quad_segs=8)

    handle = affinity.translate(
        affinity.scale(Point(0, 0).buffer(1.0, quad_segs=16),
                       xfact=0.18, yfact=0.22, origin=(0, 0)),
        yoff=h_body + 0.20,
    )
    return _scale_center(bell_body.union(handle), size_mm)
