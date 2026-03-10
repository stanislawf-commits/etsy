"""
design_agent.py - generuje pliki SVG dla produktów 3D (cuttery, stemple).

Tryby:
  mock  - szybkie placeholder SVG (do testów i CI, bez API)
  real  - generowanie przez Claude API (produkcja)

Interfejs:
  agent = create_design_agent('mock')
  result = agent.generate(topic, product_type, sizes=['S','M','L'], output_dir=Path(...))
  # result: {'success': bool, 'slug': str, 'files': [{'size', 'path', 'width_mm', 'height_mm'}]}

Uruchomienie standalone (domyślny przykład):
  python3 src/agents/design_agent.py
"""
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Literal

import svgwrite
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── stałe ────────────────────────────────────────────────────────────────────

SIZE_MM: dict[str, float] = {
    "XS": 50.0,
    "S":  60.0,
    "M":  75.0,
    "L":  90.0,
    "XL": 110.0,
}

# Grubość ścianki cuttera (mm) - jako stroke w SVG
WALL_MM = 2.5

DATA_DIR = Path(__file__).parents[2] / "data" / "products"
MODEL = "claude-sonnet-4-6"


# ── helper ────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_]+", "-", text)


def _detect_shape(topic: str) -> str:
    """Dobiera kształt bazując na słowach kluczowych tematu."""
    t = topic.lower()
    if any(w in t for w in ("mountain", "climbing", "peak", "alpine", "hill")):
        return "mountain"
    if any(w in t for w in ("heart", "love", "valentine")):
        return "heart"
    if any(w in t for w in ("star", "celestial", "astro")):
        return "star"
    if any(w in t for w in ("moon", "crescent", "lunar")):
        return "moon"
    if any(w in t for w in ("flower", "floral", "wreath", "botanical", "petal", "rose", "daisy")):
        return "floral"
    if any(w in t for w in ("leaf", "leaves", "foliage")):
        return "leaf"
    if any(w in t for w in ("butterfly", "moth")):
        return "butterfly"
    if any(w in t for w in ("mushroom", "cottagecore", "toadstool")):
        return "mushroom"
    if any(w in t for w in ("hex", "hexagon", "geometric", "honeycomb")):
        return "hexagon"
    if any(w in t for w in ("sun", "boho", "sunburst", "sunshine")):
        return "sun"
    return "rounded_rect"


# ── generatory ścieżek SVG (normalizowane: cx, cy = środek, size = promień/szerokość) ─

def _path_mountain(cx: float, cy: float, s: float) -> str:
    """Sylwetka gór - trójkąt z drugim szczytem."""
    h = s * 0.88
    w = s * 0.92
    # główny szczyt
    ax, ay = cx, cy - h / 2
    br, bb = cx + w / 2, cy + h / 2
    bl = cx - w / 2
    # drugi szczyt (lewo)
    p2x = cx - w * 0.22
    p2y = cy - h * 0.25
    p2l = cx - w * 0.46
    p2r = cx + w * 0.05
    d  = f"M {bl:.2f},{bb:.2f}"
    d += f" L {p2l:.2f},{bb:.2f}"
    d += f" L {p2x:.2f},{p2y:.2f}"
    d += f" L {p2r:.2f},{bb:.2f}"
    d += f" L {br:.2f},{bb:.2f}"
    d += f" L {ax:.2f},{ay:.2f}"
    d += " Z"
    return d


def _path_heart(cx: float, cy: float, s: float) -> str:
    """Klasyczne serce przez krzywe Beziera."""
    # Serce: szerokość ≈ 1.2s, wysokość ≈ s
    w = s
    h = s * 0.9
    top_y = cy - h * 0.15
    # dolny czubek
    tip_x, tip_y = cx, cy + h * 0.5
    # lewe i prawe górne okręgi
    lx = cx - w * 0.5
    rx = cx + w * 0.5
    # punkty kontrolne
    d = f"M {cx:.2f},{top_y:.2f}"
    d += f" C {rx:.2f},{cy - h * 0.6:.2f} {rx + w * 0.5:.2f},{cy + h * 0.1:.2f} {tip_x:.2f},{tip_y:.2f}"
    d += f" C {lx - w * 0.5:.2f},{cy + h * 0.1:.2f} {lx:.2f},{cy - h * 0.6:.2f} {cx:.2f},{top_y:.2f}"
    d += " Z"
    return d


def _path_star(cx: float, cy: float, s: float, points: int = 5) -> str:
    """Gwiazdka (domyślnie 5 ramion)."""
    r_outer = s * 0.5
    r_inner = s * 0.21
    pts = []
    for i in range(points * 2):
        angle = math.radians(i * 180 / points - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    return d


def _path_moon(cx: float, cy: float, s: float) -> str:
    """Sierp księżyca."""
    r = s * 0.46
    # outer circle - inner circle offset
    offset = r * 0.38
    d = (
        f"M {cx:.2f},{cy - r:.2f}"
        f" A {r:.2f},{r:.2f} 0 1 1 {cx:.2f},{cy + r:.2f}"
        f" A {r * 0.85:.2f},{r * 0.85:.2f} 0 0 0 {cx:.2f},{cy - r:.2f} Z"
    )
    # Prostsze podejście: dwa łuki
    ox = cx + offset
    d = (
        f"M {cx:.2f},{cy - r:.2f}"
        f" A {r:.2f},{r:.2f} 0 1 1 {cx:.2f},{cy + r:.2f}"
        f" A {r:.2f},{r:.2f} 0 0 0 {cx:.2f},{cy - r:.2f} Z"
    )
    return d


def _path_floral(cx: float, cy: float, s: float) -> str:
    """Kwiatowy wieniec - koło z płatkami."""
    # Zewnętrzny wieniec: 8 płatków
    n_petals = 8
    r_inner = s * 0.20
    r_outer = s * 0.46
    r_petal = s * 0.16
    pts_outer = []
    for i in range(n_petals):
        angle = math.radians(i * 360 / n_petals)
        px = cx + (r_inner + r_petal) * math.cos(angle)
        py = cy + (r_inner + r_petal) * math.sin(angle)
        pts_outer.append((px, py, angle))

    # Buduj ścieżkę z płatków (elipsy przybliżone łukami)
    parts = []
    for px, py, angle in pts_outer:
        # Każdy płatek to mały okrąg
        parts.append(
            f"M {px + r_petal * math.cos(angle):.2f},{py + r_petal * math.sin(angle):.2f}"
            f" A {r_petal:.2f},{r_petal:.2f} 0 1 1"
            f" {px + r_petal * math.cos(angle) - 0.01:.2f},{py + r_petal * math.sin(angle):.2f} Z"
        )
    # Środkowe koło
    parts.append(
        f"M {cx + r_inner:.2f},{cy:.2f}"
        f" A {r_inner:.2f},{r_inner:.2f} 0 1 1 {cx + r_inner - 0.01:.2f},{cy:.2f} Z"
    )
    return " ".join(parts)


def _path_leaf(cx: float, cy: float, s: float) -> str:
    """Liść - pionowy, symetryczny."""
    h = s * 0.88
    w = s * 0.44
    top = cy - h / 2
    bot = cy + h / 2
    d = (
        f"M {cx:.2f},{top:.2f}"
        f" C {cx + w:.2f},{cy - h * 0.1:.2f} {cx + w:.2f},{cy + h * 0.1:.2f} {cx:.2f},{bot:.2f}"
        f" C {cx - w:.2f},{cy + h * 0.1:.2f} {cx - w:.2f},{cy - h * 0.1:.2f} {cx:.2f},{top:.2f}"
        " Z"
    )
    return d


def _path_butterfly(cx: float, cy: float, s: float) -> str:
    """Motyl - dwie pary skrzydeł."""
    w = s * 0.48
    h = s * 0.38
    # Górne skrzydła
    d = (
        f"M {cx:.2f},{cy:.2f}"
        f" C {cx - w * 0.3:.2f},{cy - h * 1.5:.2f} {cx - w * 1.1:.2f},{cy - h * 1.0:.2f} {cx - w:.2f},{cy:.2f}"
        f" C {cx - w * 1.1:.2f},{cy + h * 0.3:.2f} {cx - w * 0.3:.2f},{cy + h * 0.5:.2f} {cx:.2f},{cy:.2f}"
        f" C {cx + w * 0.3:.2f},{cy + h * 0.5:.2f} {cx + w * 1.1:.2f},{cy + h * 0.3:.2f} {cx + w:.2f},{cy:.2f}"
        f" C {cx + w * 1.1:.2f},{cy - h * 1.0:.2f} {cx + w * 0.3:.2f},{cy - h * 1.5:.2f} {cx:.2f},{cy:.2f}"
        " Z"
    )
    return d


def _path_mushroom(cx: float, cy: float, s: float) -> str:
    """Grzyb - kapelusz i nóżka."""
    cap_r = s * 0.44
    stem_w = s * 0.22
    stem_h = s * 0.34
    top_y = cy - s * 0.18
    stem_top = cy + s * 0.18
    stem_bot = cy + s * 0.52
    # kapelusz (półkole)
    d = (
        f"M {cx - cap_r:.2f},{top_y:.2f}"
        f" A {cap_r:.2f},{cap_r:.2f} 0 0 1 {cx + cap_r:.2f},{top_y:.2f}"
        f" Q {cx + cap_r:.2f},{stem_top:.2f} {cx + stem_w:.2f},{stem_top:.2f}"
        f" L {cx + stem_w:.2f},{stem_bot:.2f}"
        f" L {cx - stem_w:.2f},{stem_bot:.2f}"
        f" L {cx - stem_w:.2f},{stem_top:.2f}"
        f" Q {cx - cap_r:.2f},{stem_top:.2f} {cx - cap_r:.2f},{top_y:.2f}"
        " Z"
    )
    return d


def _path_hexagon(cx: float, cy: float, s: float) -> str:
    """Sześciokąt foremny."""
    r = s * 0.48
    pts = []
    for i in range(6):
        angle = math.radians(i * 60 + 30)
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    return d


def _path_sun(cx: float, cy: float, s: float) -> str:
    """Słońce boho - koło z 12 promieniami."""
    r_inner = s * 0.22
    r_outer = s * 0.46
    r_tip = s * 0.10
    n = 12
    pts = []
    for i in range(n * 2):
        angle = math.radians(i * 180 / n)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    return d


def _path_rounded_rect(cx: float, cy: float, s: float) -> str:
    """Zaokrąglony prostokąt (fallback)."""
    w = s * 0.85
    h = s * 0.70
    r = s * 0.12
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = cx + w / 2, cy + h / 2
    d = (
        f"M {x0 + r:.2f},{y0:.2f}"
        f" L {x1 - r:.2f},{y0:.2f} Q {x1:.2f},{y0:.2f} {x1:.2f},{y0 + r:.2f}"
        f" L {x1:.2f},{y1 - r:.2f} Q {x1:.2f},{y1:.2f} {x1 - r:.2f},{y1:.2f}"
        f" L {x0 + r:.2f},{y1:.2f} Q {x0:.2f},{y1:.2f} {x0:.2f},{y1 - r:.2f}"
        f" L {x0:.2f},{y0 + r:.2f} Q {x0:.2f},{y0:.2f} {x0 + r:.2f},{y0:.2f}"
        " Z"
    )
    return d


SHAPE_BUILDERS = {
    "mountain":     _path_mountain,
    "heart":        _path_heart,
    "star":         _path_star,
    "moon":         _path_moon,
    "floral":       _path_floral,
    "leaf":         _path_leaf,
    "butterfly":    _path_butterfly,
    "mushroom":     _path_mushroom,
    "hexagon":      _path_hexagon,
    "sun":          _path_sun,
    "rounded_rect": _path_rounded_rect,
}


# ── generowanie SVG ───────────────────────────────────────────────────────────

def _make_svg_mock(
    topic: str,
    product_type: str,
    size: str,
    out_path: Path,
) -> dict:
    """Generuje placeholder SVG z kształtem bazującym na temacie."""
    size_mm = SIZE_MM.get(size.upper(), 75.0)
    shape_key = _detect_shape(topic)
    builder = SHAPE_BUILDERS[shape_key]

    cx = size_mm / 2
    cy = size_mm / 2
    path_d = builder(cx, cy, size_mm * 0.46)

    dwg = svgwrite.Drawing(
        str(out_path),
        size=(f"{size_mm}mm", f"{size_mm}mm"),
        viewBox=f"0 0 {size_mm} {size_mm}",
        profile="full",
    )
    # tło (opcjonalne - przezroczyste dla druku)
    dwg.add(dwg.rect(insert=(0, 0), size=(f"{size_mm}mm", f"{size_mm}mm"), fill="white"))

    # cień / kontur produktu
    if product_type == "cutter":
        # Dla cuttera: tylko obrys (stroke), fill=none
        dwg.add(dwg.path(
            d=path_d,
            fill="none",
            stroke="#1a1a1a",
            stroke_width=f"{WALL_MM}mm",
            stroke_linejoin="round",
            stroke_linecap="round",
        ))
    else:
        # Dla stampa: wypełniony kształt
        dwg.add(dwg.path(
            d=path_d,
            fill="#2d2d2d",
            stroke="#1a1a1a",
            stroke_width=f"{WALL_MM * 0.5}mm",
        ))

    # etykieta (debug/meta)
    label = f"{topic} | {product_type.upper()} | {size}"
    dwg.add(dwg.text(
        label,
        insert=(f"{size_mm / 2}mm", f"{size_mm * 0.96}mm"),
        text_anchor="middle",
        font_size="3px",
        fill="#888888",
        font_family="sans-serif",
    ))

    dwg.save(pretty=True)
    log.info("Saved SVG: %s (%.0fmm, shape=%s)", out_path, size_mm, shape_key)

    return {
        "size": size,
        "path": str(out_path),
        "width_mm": size_mm,
        "height_mm": size_mm,
        "shape": shape_key,
    }


def _make_svg_real(
    topic: str,
    product_type: str,
    size: str,
    out_path: Path,
) -> dict:
    """
    Generuje SVG przez Claude API - Claude opisuje kształt jako SVG path.
    Fallback do mock jeśli API niedostępne.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set – falling back to mock SVG")
        return _make_svg_mock(topic, product_type, size, out_path)

    size_mm = SIZE_MM.get(size.upper(), 75.0)
    cx = size_mm / 2
    cy = size_mm / 2
    s = size_mm * 0.44

    prompt = f"""You are an SVG path designer for 3D-printed cookie cutters.

Generate a single clean SVG path (d attribute only) for a "{topic}" {product_type} silhouette.

Constraints:
- ViewBox: 0 0 {size_mm} {size_mm} (units = mm)
- Center: ({cx:.1f}, {cy:.1f})
- Max radius / half-size: {s:.1f}mm
- Use M, L, C, A, Q, Z commands only
- Must be a single closed path (end with Z)
- For a cutter: simple outline silhouette, not too detailed
- Output ONLY the d attribute value, nothing else, no quotes, no markdown

Example format: M 37.5,10.0 L 65.0,65.0 L 10.0,65.0 Z
"""

    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        path_d = msg.content[0].text.strip()
        # walidacja minimalna
        if not path_d.upper().startswith("M") or "Z" not in path_d.upper():
            raise ValueError(f"Invalid path returned: {path_d[:80]}")
    except Exception as e:
        log.warning("Claude API path generation failed (%s) – falling back to mock", e)
        return _make_svg_mock(topic, product_type, size, out_path)

    dwg = svgwrite.Drawing(
        str(out_path),
        size=(f"{size_mm}mm", f"{size_mm}mm"),
        viewBox=f"0 0 {size_mm} {size_mm}",
        profile="full",
    )
    dwg.add(dwg.rect(insert=(0, 0), size=(f"{size_mm}mm", f"{size_mm}mm"), fill="white"))

    if product_type == "cutter":
        dwg.add(dwg.path(d=path_d, fill="none", stroke="#1a1a1a", stroke_width=f"{WALL_MM}mm"))
    else:
        dwg.add(dwg.path(d=path_d, fill="#2d2d2d", stroke="#1a1a1a", stroke_width=f"{WALL_MM * 0.5}mm"))

    dwg.save(pretty=True)
    log.info("Saved real SVG: %s (%.0fmm)", out_path, size_mm)

    return {
        "size": size,
        "path": str(out_path),
        "width_mm": size_mm,
        "height_mm": size_mm,
        "shape": "claude_generated",
    }



def _make_svg_dalle3(
    topic: str,
    product_type: str,
    size: str,
    out_path: Path,
) -> dict:
    """
    Generuje obraz przez DALL-E 3 i zapisuje jako PNG + wrapper SVG.
    Fallback do mock jesli API niedostepne lub blad.
    """
    import requests as _requests

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set – falling back to mock SVG")
        return _make_svg_mock(topic, product_type, size, out_path)

    size_mm = SIZE_MM.get(size.upper(), 75.0)
    prompt = (
        f"{topic}, flat 2D illustration, cookie cutter outline, "
        "black lines on white background, no shading, no gradients, "
        "clean vector style, suitable for 3D printing"
    )

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            style="natural",
            n=1,
        )
        img_url = response.data[0].url
        log.info("DALL-E 3 URL: %s", img_url[:60])

        # Pobierz PNG
        png_path = out_path.parent / (out_path.stem.replace(".svg", "") + "_dalle_raw.png")
        resp = _requests.get(img_url, timeout=30)
        resp.raise_for_status()
        png_path.write_bytes(resp.content)
        log.info("Saved DALL-E PNG: %s (%d B)", png_path, len(resp.content))

        # Wrapper SVG z osadzonym obrazem (do podgladem)
        size_str = f"{size_mm}mm"
        svg_content = (
            f'''<?xml version="1.0" encoding="utf-8"?>\n'''
            f'''<svg xmlns="http://www.w3.org/2000/svg" '''
            f'''xmlns:xlink="http://www.w3.org/1999/xlink" '''
            f'''width="{size_str}" height="{size_str}" '''
            f'''viewBox="0 0 {size_mm} {size_mm}">\n'''
            f'''  <image href="{png_path.name}" x="0" y="0" '''
            f'''width="{size_mm}" height="{size_mm}"/>\n'''
            f'''  <text x="{size_mm/2}" y="{size_mm*0.97}" '''
            f'''text-anchor="middle" font-size="3px" fill="#888">'''
            f'''{topic} | DALL-E 3 | {size}</text>\n'''
            f'''</svg>\n'''
        )
        out_path.write_text(svg_content, encoding="utf-8")
        log.info("Saved dalle3 SVG wrapper: %s", out_path)

        return {
            "size": size,
            "path": str(out_path),
            "png_path": str(png_path),
            "width_mm": size_mm,
            "height_mm": size_mm,
            "shape": "dalle3_generated",
        }

    except Exception as e:
        log.warning("DALL-E 3 generation failed (%s) – falling back to mock", e)
        return _make_svg_mock(topic, product_type, size, out_path)


# ── klasa agenta ─────────────────────────────────────────────────────────────

class DesignAgent:
    def __init__(self, mode: str = "mock"):
        self.mode = mode
        if mode == "real":
            self._make_svg = _make_svg_real
        elif mode in ("dalle3", "auto"):
            self._make_svg = _make_svg_dalle3
        else:
            self._make_svg = _make_svg_mock

    def generate(
        self,
        topic: str,
        product_type: str = "cutter",
        sizes: list[str] | None = None,
        output_dir: Path | None = None,
    ) -> dict:
        """
        Generuje pliki SVG dla każdego rozmiaru.

        Args:
            topic:        Temat produktu, np. "floral wreath"
            product_type: "cutter" | "stamp" | "set"
            sizes:        Lista rozmiarów, np. ['S', 'M', 'L']
            output_dir:   Katalog nadrzędny (domyślnie data/products/)

        Returns:
            {
              'success': bool,
              'slug': str,
              'topic': str,
              'product_type': str,
              'mode': str,
              'files': [{'size', 'path', 'width_mm', 'height_mm', 'shape'}],
              'error': str  # tylko gdy success=False
            }
        """
        if sizes is None:
            sizes = ["M"]
        if output_dir is None:
            output_dir = DATA_DIR

        slug = _slugify(f"{topic}-{product_type}")
        source_dir = Path(output_dir) / slug / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        files = []
        errors = []

        for size in sizes:
            size_up = size.upper()
            if size_up not in SIZE_MM:
                log.warning("Unknown size '%s' – skipping", size)
                errors.append(f"Unknown size: {size}")
                continue

            filename = f"{slug}-{size_up}.svg"
            out_path = source_dir / filename

            try:
                file_info = self._make_svg(topic, product_type, size_up, out_path)
                files.append(file_info)
            except Exception as e:
                log.error("Failed to generate SVG for size %s: %s", size, e)
                errors.append(f"Size {size}: {e}")

        success = len(files) > 0

        result = {
            "success": success,
            "slug": slug,
            "topic": topic,
            "product_type": product_type,
            "mode": self.mode,
            "files": files,
        }
        if errors:
            result["errors"] = errors

        # zapis metadanych do output_dir/<slug>/design.json
        meta_path = Path(output_dir) / slug / "design.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        log.info("Saved design meta: %s", meta_path)

        return result


# ── factory ───────────────────────────────────────────────────────────────────

def create_design_agent(mode: str = "mock") -> DesignAgent:
    """
    Tworzy instancję DesignAgent.

    Args:
        mode: 'mock'   - SVG z predefiniowanych ksztaltow (bez API)
              'real'   - SVG przez Claude API (produkcja)
              'dalle3' - obraz przez DALL-E 3 (wymaga OPENAI_API_KEY)
              'auto'   - dalle3 jesli OPENAI_API_KEY dostepny, inaczej mock
    """
    return DesignAgent(mode=mode)


# ── standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    agent = create_design_agent("mock")
    result = agent.generate(
        topic="floral wreath",
        product_type="cutter",
        sizes=["S", "M", "L"],
        output_dir=DATA_DIR,
    )

    print(f"\n{'OK' if result['success'] else 'FAIL'} — slug: {result['slug']}")
    for f in result["files"]:
        print(f"  [{f['size']}] {f['width_mm']:.0f}mm  →  {f['path']}")
