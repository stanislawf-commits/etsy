"""
src/shapes/stamp_elements.py — generuje wzory stempla (Claude JSON → Shapely).

Publiczne API:
    plan_stamp(product: dict) -> dict
        Wywołuje Claude (FAST_MODEL) z opisem tematu, zwraca JSON plan elementów.
        Przy błędzie API — fallback na mock_plan().

    build_relief(plan: dict, base_poly=None) -> Polygon
        Buduje Shapely Polygon z JSON planu.
        Jeśli base_poly podany — przycina relief do wnętrza bazy.
        Zawsze zwraca pojedynczy Polygon (nie MultiPolygon).

    mock_plan(topic, size_mm, n=7) -> dict
        Plan bez Claude API — kwiat centralny + płatki. Dla testów/CI.

Obsługiwane typy elementów:
    circle, dot, ellipse, petal, leaf, star5, diamond, heart_small, teardrop, ring
"""
import logging
import math

from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from src.utils.claude_client import claude_json, FAST_MODEL

log = logging.getLogger(__name__)

ELEMENT_TYPES = (
    "circle", "dot", "ellipse", "petal", "leaf",
    "star5", "diamond", "heart_small", "teardrop", "ring",
)

_SYSTEM = (
    "Jesteś generatorem wzorów do stempli ciasteczkowych. "
    "Odpowiadasz TYLKO poprawnym JSON bez komentarzy ani markdown."
)

_PROMPT_TMPL = """\
Zaprojektuj wzór stempla/reliefu do formy ciasteczkowej.

Temat: {topic}
Kształt bazy: {base_shape} ({size_mm}×{size_mm} mm, środek (0,0))
Obszar aktywny: ≤ {inner_mm:.0f} mm od centrum (zostaw margines ~{margin_mm:.0f} mm)

Zasady:
1. Zaprojektuj {n} elementów.
2. Każdy element ≥ 3 mm (rozmiar = diameter lub główny wymiar).
3. Elementy powinny nachodzić lub być blisko siebie — bez izolowanych wysp.
4. Wzór ma oddawać temat "{topic}".
5. Nazwy typów: circle, dot, ellipse, petal, leaf, star5, diamond, heart_small, teardrop, ring.

Zwróć TYLKO JSON (bez markdown):
{{
  "elements": [
    {{"type": "<typ>", "x": <mm>, "y": <mm>, "size": <mm>, "rotation": <deg>}},
    ...
  ]
}}
"""


# ── Publiczne API ──────────────────────────────────────────────────────────────

def plan_stamp(product: dict) -> dict:
    """
    Wywołuje Claude i zwraca JSON plan wzoru stempla.

    Args:
        product: dict z polami slug, stamp_topic (lub topic), base_shape, size_mm.

    Returns:
        dict: {topic, base_shape, size_mm, elements: [{type,x,y,size,rotation},...]}
    """
    topic      = product.get("stamp_topic") or product.get("topic", "flowers")
    base_shape = product.get("base_shape", "heart")
    size_mm    = float(product.get("size_mm", 75.0))
    n_elem     = int(product.get("n_elements", 9))
    inner_mm   = size_mm * 0.72
    margin_mm  = size_mm * 0.14

    prompt = _PROMPT_TMPL.format(
        topic=topic, base_shape=base_shape,
        size_mm=size_mm, inner_mm=inner_mm,
        margin_mm=margin_mm, n=n_elem,
    )

    try:
        plan = dict(claude_json(prompt, model=FAST_MODEL, max_tokens=1024, system=_SYSTEM))
        plan.setdefault("topic",      topic)
        plan.setdefault("base_shape", base_shape)
        plan.setdefault("size_mm",    size_mm)
        log.info("plan_stamp OK: %d elements, topic=%r", len(plan.get("elements", [])), topic)
        return plan
    except Exception as exc:
        log.warning("plan_stamp Claude failed (%s) — fallback mock_plan", exc)
        return mock_plan(topic, size_mm, n_elem)


def build_relief(plan: dict, base_poly=None) -> Polygon:
    """
    Buduje Shapely Polygon z JSON planu wzoru stempla.

    Args:
        plan:      dict z kluczem 'elements' (output plan_stamp lub mock_plan).
        base_poly: opcjonalny Shapely Polygon bazy — relief zostanie przycięty.

    Returns:
        Polygon gotowy do stamp_scad() / generate_stamp_stl().
    """
    size_mm  = float(plan.get("size_mm", 75.0))
    elements = plan.get("elements", [])

    shapes = [_build_element(e) for e in elements]
    shapes = [s for s in shapes if s is not None and not s.is_empty]

    if not shapes:
        log.warning("build_relief: brak elementów — fallback circle")
        return Point(0, 0).buffer(size_mm * 0.20, quad_segs=32)

    relief = unary_union(shapes)

    # MultiPolygon → spróbuj połączyć małym buffer
    if relief.geom_type == "MultiPolygon":
        merged = relief.buffer(1.5).buffer(-1.1)
        if merged.geom_type != "MultiPolygon":
            relief = merged
        else:
            relief = max(merged.geoms, key=lambda g: g.area)
            log.debug("build_relief: MultiPolygon — wzięto największy fragment")

    # Przytnij do wnętrza bazy
    if base_poly is not None:
        margin  = size_mm * 0.06
        inner   = base_poly.buffer(-margin)
        clipped = relief.intersection(inner)
        if not clipped.is_empty:
            relief = clipped
            if relief.geom_type == "MultiPolygon":
                relief = max(relief.geoms, key=lambda g: g.area)

    return relief if relief.geom_type == "Polygon" else relief.convex_hull


def mock_plan(topic: str, size_mm: float, n: int = 7) -> dict:
    """
    Generuje prosty plan bez Claude API (testy / tryb mock).
    Wzór: kwiat centralny z płatkami i małymi kropkami.

    Args:
        topic:   Temat (tylko metadane, nie wpływa na kształt).
        size_mm: Wymiar docelowy bazy.
        n:       Przybliżona liczba elementów.

    Returns:
        dict z kluczem 'elements'.
    """
    r_center = size_mm * 0.10
    r_petal  = size_mm * 0.09
    r_orbit  = size_mm * 0.22
    r_dot    = size_mm * 0.04
    n_petals = max(3, min(n - 1, 6))

    elements: list[dict] = [
        {"type": "circle", "x": 0.0, "y": 0.0,
         "size": round(r_center * 2, 2), "rotation": 0},
    ]
    for i in range(n_petals):
        angle = 2 * math.pi * i / n_petals
        elements.append({
            "type": "petal",
            "x":    round(r_orbit * math.cos(angle), 2),
            "y":    round(r_orbit * math.sin(angle), 2),
            "size": round(r_petal * 2, 2),
            "rotation": round(math.degrees(angle), 1),
        })
    # Małe kropki między płatkami
    n_dots = min(n_petals, 4)
    for i in range(n_dots):
        angle = 2 * math.pi * (i + 0.5) / n_petals
        elements.append({
            "type": "dot",
            "x":    round(r_orbit * 1.65 * math.cos(angle), 2),
            "y":    round(r_orbit * 1.65 * math.sin(angle), 2),
            "size": round(r_dot * 2, 2),
            "rotation": 0,
        })

    return {
        "topic":      topic,
        "base_shape": "generic",
        "size_mm":    size_mm,
        "elements":   elements,
    }


# ── Element builders ───────────────────────────────────────────────────────────

def _build_element(el: dict) -> Polygon | None:
    """Buduje pojedynczy element Shapely wyśrodkowany w (x, y)."""
    el_type  = el.get("type", "circle")
    x        = float(el.get("x", 0))
    y        = float(el.get("y", 0))
    size     = max(float(el.get("size", 5.0)), 1.0)
    rotation = float(el.get("rotation", 0))
    r        = size / 2

    try:
        shape = _shape_by_type(el_type, r)
        if shape is None or shape.is_empty:
            return None
        if rotation:
            shape = affinity.rotate(shape, rotation, origin=(0, 0))
        return affinity.translate(shape, xoff=x, yoff=y)
    except Exception as exc:
        log.debug("_build_element failed type=%r: %s", el_type, exc)
        return None


def _shape_by_type(el_type: str, r: float) -> Polygon | None:
    """Zwraca kształt bazowy wyśrodkowany w (0,0) z 'promieniem' r."""

    if el_type in ("circle", "dot"):
        return Point(0, 0).buffer(r, quad_segs=16)

    if el_type == "ellipse":
        return affinity.scale(
            Point(0, 0).buffer(r, quad_segs=16), xfact=1.0, yfact=1.6, origin=(0, 0)
        )

    if el_type == "petal":
        return affinity.scale(
            Point(0, 0).buffer(r, quad_segs=16), xfact=0.42, yfact=1.0, origin=(0, 0)
        )

    if el_type == "leaf":
        return affinity.scale(
            Point(0, 0).buffer(r, quad_segs=16), xfact=0.28, yfact=1.0, origin=(0, 0)
        )

    if el_type == "star5":
        n = 5
        r_in = r * 0.42
        pts = [
            (( r if i % 2 == 0 else r_in) * math.cos(math.pi * i / n - math.pi / 2),
             ( r if i % 2 == 0 else r_in) * math.sin(math.pi * i / n - math.pi / 2))
            for i in range(n * 2)
        ]
        return Polygon(pts).buffer(r * 0.05, join_style="round", quad_segs=4)

    if el_type == "diamond":
        pts = [(0, r), (r * 0.6, 0), (0, -r), (-r * 0.6, 0)]
        return Polygon(pts).buffer(r * 0.04, join_style="round", quad_segs=4)

    if el_type == "heart_small":
        pts = []
        for i in range(32):
            t = 2 * math.pi * i / 32
            hx = 16 * math.sin(t) ** 3
            hy = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append((hx, -hy))
        raw = Polygon(pts)
        b   = raw.bounds
        sc  = (r * 2) / max(b[2] - b[0], b[3] - b[1], 1e-9)
        return affinity.scale(raw, xfact=sc, yfact=sc, origin=(0, 0))

    if el_type == "teardrop":
        pts = [
            (r * (1 - 0.3 * math.cos(2 * math.pi * i / 32)) * math.sin(2 * math.pi * i / 32),
             r * (1 - 0.3 * math.cos(2 * math.pi * i / 32)) * math.cos(2 * math.pi * i / 32)
             - r * 0.15)
            for i in range(32)
        ]
        return Polygon(pts)

    if el_type == "ring":
        outer = Point(0, 0).buffer(r, quad_segs=32)
        inner = Point(0, 0).buffer(r * 0.58, quad_segs=32)
        return outer.difference(inner)

    # Fallback
    return Point(0, 0).buffer(r, quad_segs=16)
