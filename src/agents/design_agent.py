"""
design_agent.py - generuje pliki SVG dla produktów 3D (cuttery, stemple).

Tryby:
  mock  - szybkie placeholder SVG (do testów i CI, bez API)
  real  - generowanie przez Claude API (produkcja)
  auto  - Claude API jeśli ANTHROPIC_API_KEY dostępny, inaczej mock

Interfejs:
  agent = create_design_agent('mock')
  result = agent.generate(topic, product_type, sizes=['S','M','L'], output_dir=Path(...))
  # result: {'success': bool, 'slug': str, 'files': [{'size', 'path', 'width_mm', 'height_mm'}]}

Uruchomienie standalone:
  python3 src/agents/design_agent.py
"""
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── stałe ────────────────────────────────────────────────────────────────────

SIZE_MM: dict[str, float] = {
    "XS":   50.0,
    "S":    60.0,
    "M":    75.0,
    "L":    90.0,
    "XL":  110.0,
    "XXXL": 150.0,
}

# Grubość ścianki cuttera (mm) - jako stroke w SVG
WALL_MM = 2.5

DATA_DIR = Path(__file__).parents[2] / "data" / "products"
MODEL = "claude-opus-4-6"

# Liczba prób generowania przez API
_MAX_RETRIES = 3

# Kształty z twarzą (oczy + uśmiech)
CREATURE_SHAPES = {"cat", "dog", "rabbit", "hen", "bear", "owl", "llama", "gingerbread", "mushroom"}

# Kształty roślinne/jedzenie (dekoracyjne kropki)
PLANT_FOOD_SHAPES = {"heart", "floral", "apple", "strawberry", "tulip"}


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
    if any(w in t for w in ("pumpkin", "halloween", "gourd")):
        return "pumpkin"
    if any(w in t for w in ("christmas", "xmas", "tree", "pine", "fir")):
        return "christmas_tree"
    if any(w in t for w in ("snowflake", "snow", "winter", "ice crystal")):
        return "snowflake"
    if any(w in t for w in ("gingerbread", "ginger", "man", "person", "human")):
        return "gingerbread"
    # S2.5 new shapes
    if any(w in t for w in ("cat", "kitten", "kitty")):
        return "cat"
    if any(w in t for w in ("dog", "puppy", "dachshund", "poodle")):
        return "dog"
    if any(w in t for w in ("rabbit", "bunny", "hare", "easter bunny")):
        return "rabbit"
    if any(w in t for w in ("hen", "chicken", "chick", "rooster")):
        return "hen"
    if any(w in t for w in ("bear", "teddy")):
        return "bear"
    if any(w in t for w in ("owl",)):
        return "owl"
    if any(w in t for w in ("llama", "alpaca")):
        return "llama"
    if any(w in t for w in ("fish", "goldfish")):
        return "fish"
    if any(w in t for w in ("bird", "robin", "sparrow")):
        return "bird"
    if any(w in t for w in ("apple",)):
        return "apple"
    if any(w in t for w in ("cactus", "succulent")):
        return "cactus"
    if any(w in t for w in ("strawberry",)):
        return "strawberry"
    if any(w in t for w in ("tulip",)):
        return "tulip"
    if any(w in t for w in ("easter", "egg")):
        return "easter_egg"
    if any(w in t for w in ("crown", "princess", "queen", "royal")):
        return "crown"
    if any(w in t for w in ("cookie", "biscuit", "shortbread")):
        return "cookie"
    return "rounded_rect"


# ── walidacja ─────────────────────────────────────────────────────────────────

def _validate_path(path_d: str, size_mm: float) -> tuple[bool, str]:
    """
    Waliduje SVG path pod kątem druku 3D.

    Returns:
        (ok: bool, reason: str)
    """
    d = path_d.strip()
    d_upper = d.upper()

    # Musi zaczynać się od M i kończyć na Z
    if not d_upper.lstrip().startswith("M"):
        return False, "Path must start with M command"
    if not d_upper.rstrip().endswith("Z"):
        return False, "Path must end with Z command"

    # Każda subpath musi kończyć się Z (sprawdzamy czy ostatni Z zamyka całość)
    # Multiple subpaths dozwolone — liczymy M i Z, powinno być tyle samo
    m_count = len(re.findall(r"(?<![A-Za-z])M", d_upper))
    z_count = len(re.findall(r"(?<![A-Za-z])Z", d_upper))
    if m_count != z_count:
        return False, f"Subpath count mismatch: {m_count} M commands but {z_count} Z commands — each subpath must end with Z"

    # Minimalna liczba punktów współrzędnych
    # Akceptuj zarówno "x,y" jak i "x y" (format potrace)
    coords = re.findall(r"-?\d+\.?\d*\s*[,\s]\s*-?\d+\.?\d*", d)
    if len(coords) < 3:
        return False, f"Too few coordinate pairs ({len(coords)}) — need at least 3 for a recognizable shape"

    # Sprawdź zakresy współrzędnych
    margin = size_mm * 0.15
    for coord in coords:
        parts = re.split(r"[\s,]+", coord.strip())
        try:
            x, y = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            continue
        if not (-margin <= x <= size_mm + margin):
            return False, f"X coordinate {x:.1f} out of bounds [0, {size_mm:.0f}]"
        if not (-margin <= y <= size_mm + margin):
            return False, f"Y coordinate {y:.1f} out of bounds [0, {size_mm:.0f}]"

    return True, "OK"


# ── generatory ścieżek SVG ────────────────────────────────────────────────────

def _path_mountain(cx: float, cy: float, s: float) -> str:
    """Sylwetka gór - trójkąt z drugim szczytem."""
    h = s * 0.88
    w = s * 0.92
    ax, ay = cx, cy - h / 2
    br, bb = cx + w / 2, cy + h / 2
    bl = cx - w / 2
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
    """Klasyczne serce przez krzywe Beziera — wiarygodny kształt."""
    w = s * 0.96
    h = s * 0.90
    # dolny czubek
    tip_x, tip_y = cx, cy + h * 0.52
    # górne wcięcie
    dip_x, dip_y = cx, cy - h * 0.02
    # lewe i prawe górne szczyty
    lhx, lhy = cx - w * 0.50, cy - h * 0.28
    rhx, rhy = cx + w * 0.50, cy - h * 0.28
    # punkty startowe na górze (środek wcięcia)
    d  = f"M {dip_x:.2f},{dip_y:.2f}"
    # prawa strona: z wcięcia do prawego szczytu do czubka
    d += (f" C {cx + w * 0.12:.2f},{cy - h * 0.55:.2f}"
          f" {cx + w * 0.90:.2f},{cy - h * 0.55:.2f}"
          f" {rhx:.2f},{rhy:.2f}")
    d += (f" C {cx + w * 1.05:.2f},{cy + h * 0.05:.2f}"
          f" {cx + w * 0.60:.2f},{cy + h * 0.35:.2f}"
          f" {tip_x:.2f},{tip_y:.2f}")
    # lewa strona: z czubka do lewego szczytu do wcięcia
    d += (f" C {cx - w * 0.60:.2f},{cy + h * 0.35:.2f}"
          f" {cx - w * 1.05:.2f},{cy + h * 0.05:.2f}"
          f" {lhx:.2f},{lhy:.2f}")
    d += (f" C {cx - w * 0.90:.2f},{cy - h * 0.55:.2f}"
          f" {cx - w * 0.12:.2f},{cy - h * 0.55:.2f}"
          f" {dip_x:.2f},{dip_y:.2f}")
    d += " Z"
    return d


def _path_star(cx: float, cy: float, s: float, points: int = 5) -> str:
    """Gwiazdka (domyślnie 5 ramion)."""
    r_outer = s * 0.50
    r_inner = s * 0.21
    pts = []
    for i in range(points * 2):
        angle = math.radians(i * 180 / points - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    return d


def _path_moon(cx: float, cy: float, s: float) -> str:
    """
    Sierp księżyca — bezier approximation (bez łuków A, ≥8 punktów).
    Zewnętrzny okrąg (prawa strona) + wewnętrzny okrąg przesunięty w prawo.
    """
    r   = s * 0.46
    ri  = r * 0.82   # promień okręgu wewnętrznego (wycięcia)
    off = r * 0.38   # przesunięcie środka wewnętrznego okręgu w prawo
    k   = 0.5523     # stała aproksymacji Beziera dla ćwiartek koła

    d = (
        f"M {cx:.2f},{cy - r:.2f}"
        f" C {cx + r*k:.2f},{cy - r:.2f} {cx + r:.2f},{cy - r*k:.2f} {cx + r:.2f},{cy:.2f}"
        f" C {cx + r:.2f},{cy + r*k:.2f} {cx + r*k:.2f},{cy + r:.2f} {cx:.2f},{cy + r:.2f}"
        f" C {cx + off - ri*k:.2f},{cy + ri:.2f} {cx + off - ri:.2f},{cy + ri*k:.2f} {cx + off - ri:.2f},{cy:.2f}"
        f" C {cx + off - ri:.2f},{cy - ri*k:.2f} {cx + off - ri*k:.2f},{cy - ri:.2f} {cx:.2f},{cy - r:.2f}"
        " Z"
    )
    return d


def _path_floral(cx: float, cy: float, s: float) -> str:
    """
    Kwiatowy wieniec — 8 płatków jako jedna zamknięta ścieżka.
    Płatki tworzone krzywymi Beziera — brak zdegenerowanych łuków.
    """
    n_petals = 8
    r_outer = s * 0.46
    r_inner = s * 0.28

    pts: list[tuple[float, float]] = []
    for i in range(n_petals * 2):
        angle = math.radians(i * 180 / n_petals - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    first_mid_x = (pts[-1][0] + pts[0][0]) / 2
    first_mid_y = (pts[-1][1] + pts[0][1]) / 2
    d = f"M {first_mid_x:.2f},{first_mid_y:.2f}"

    for i in range(len(pts)):
        ctrl = pts[i]
        nxt  = pts[(i + 1) % len(pts)]
        mid_x = (ctrl[0] + nxt[0]) / 2
        mid_y = (ctrl[1] + nxt[1]) / 2
        d += f" Q {ctrl[0]:.2f},{ctrl[1]:.2f} {mid_x:.2f},{mid_y:.2f}"

    d += " Z"
    return d


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
    cap_r  = s * 0.44
    stem_w = s * 0.22
    stem_h = s * 0.34
    top_y    = cy - s * 0.18
    stem_top = cy + s * 0.18
    stem_bot = cy + s * 0.52
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
    """Słońce boho - koło z 12 promieniami (gwiazdka 12-ramienna)."""
    n = 12
    r_outer = s * 0.46
    r_inner = s * 0.28
    pts = []
    for i in range(n * 2):
        angle = math.radians(i * 180 / n - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    first_mid_x = (pts[-1][0] + pts[0][0]) / 2
    first_mid_y = (pts[-1][1] + pts[0][1]) / 2
    d = f"M {first_mid_x:.2f},{first_mid_y:.2f}"
    for i in range(len(pts)):
        ctrl = pts[i]
        nxt  = pts[(i + 1) % len(pts)]
        mid_x = (ctrl[0] + nxt[0]) / 2
        mid_y = (ctrl[1] + nxt[1]) / 2
        d += f" Q {ctrl[0]:.2f},{ctrl[1]:.2f} {mid_x:.2f},{mid_y:.2f}"
    d += " Z"
    return d


def _path_pumpkin(cx: float, cy: float, s: float) -> str:
    """Dynia halloween — 4 segmenty i szypułka."""
    w = s * 0.88
    h = s * 0.76
    st_w = s * 0.10
    st_h = s * 0.22
    top_y = cy - h / 2
    bot_y = cy + h / 2

    d = (
        f"M {cx - st_w:.2f},{top_y:.2f}"
        f" L {cx - st_w:.2f},{top_y - st_h:.2f}"
        f" L {cx + st_w:.2f},{top_y - st_h:.2f}"
        f" L {cx + st_w:.2f},{top_y:.2f}"
        f" C {cx + w * 0.25:.2f},{top_y:.2f} {cx + w * 0.50:.2f},{cy - h * 0.40:.2f} {cx + w / 2:.2f},{cy:.2f}"
        f" C {cx + w * 0.50:.2f},{cy + h * 0.40:.2f} {cx + w * 0.25:.2f},{bot_y:.2f} {cx + st_w:.2f},{bot_y:.2f}"
        f" L {cx - st_w:.2f},{bot_y:.2f}"
        f" C {cx - w * 0.25:.2f},{bot_y:.2f} {cx - w * 0.50:.2f},{cy + h * 0.40:.2f} {cx - w / 2:.2f},{cy:.2f}"
        f" C {cx - w * 0.50:.2f},{cy - h * 0.40:.2f} {cx - w * 0.25:.2f},{top_y:.2f} {cx - st_w:.2f},{top_y:.2f}"
        " Z"
    )
    return d


def _path_christmas_tree(cx: float, cy: float, s: float) -> str:
    """Choinka — trzy warstwy trójkątów + pień."""
    h = s * 0.88
    top_y = cy - h / 2
    bot_y = cy + h / 2
    trunk_w = s * 0.12
    trunk_h = s * 0.18

    w1 = s * 0.86
    w2 = s * 0.62
    w3 = s * 0.38
    y1 = bot_y - trunk_h
    y2 = y1 - h * 0.28
    y3 = y2 - h * 0.25

    d = (
        f"M {cx - trunk_w:.2f},{bot_y:.2f}"
        f" L {cx - trunk_w:.2f},{y1:.2f}"
        f" L {cx - w1 / 2:.2f},{y1:.2f}"
        f" L {cx - w2 / 2:.2f},{y2:.2f}"
        f" L {cx - w3 / 2:.2f},{y2:.2f}"
        f" L {cx:.2f},{top_y:.2f}"
        f" L {cx + w3 / 2:.2f},{y2:.2f}"
        f" L {cx + w2 / 2:.2f},{y2:.2f}"
        f" L {cx + w1 / 2:.2f},{y1:.2f}"
        f" L {cx + trunk_w:.2f},{y1:.2f}"
        f" L {cx + trunk_w:.2f},{bot_y:.2f}"
        " Z"
    )
    return d


def _path_snowflake(cx: float, cy: float, s: float) -> str:
    """Płatek śniegu — 6 ramion z gałęziami."""
    n = 6
    r_arm  = s * 0.46
    r_base = s * 0.08
    r_branch = s * 0.20
    branch_off = s * 0.22

    pts: list[tuple[float, float]] = []
    for i in range(n):
        angle_arm   = math.radians(i * 60 - 90)
        angle_left  = math.radians(i * 60 - 90 + 60)
        angle_right = math.radians(i * 60 - 90 - 60)

        tip_x = cx + r_arm * math.cos(angle_arm)
        tip_y = cy + r_arm * math.sin(angle_arm)
        bl_x = cx + branch_off * math.cos(angle_arm) + r_branch * math.cos(angle_left)
        bl_y = cy + branch_off * math.sin(angle_arm) + r_branch * math.sin(angle_left)
        br_x = cx + branch_off * math.cos(angle_arm) + r_branch * math.cos(angle_right)
        br_y = cy + branch_off * math.sin(angle_arm) + r_branch * math.sin(angle_right)
        base_x = cx + branch_off * math.cos(angle_arm)
        base_y = cy + branch_off * math.sin(angle_arm)

        pts += [
            (cx + r_base * math.cos(angle_arm), cy + r_base * math.sin(angle_arm)),
            (bl_x, bl_y), (base_x, base_y), (br_x, br_y),
            (base_x, base_y),
            (tip_x, tip_y),
        ]

    d = f"M {pts[0][0]:.2f},{pts[0][1]:.2f}"
    for p in pts[1:]:
        d += f" L {p[0]:.2f},{p[1]:.2f}"
    d += " Z"
    return d


def _path_gingerbread(cx: float, cy: float, s: float) -> str:
    """Ludzik z piernika — głowa, tułów, ręce, nogi."""
    head_r  = s * 0.18
    body_w  = s * 0.32
    body_h  = s * 0.28
    arm_w   = s * 0.36
    arm_h   = s * 0.10
    leg_w   = s * 0.14
    leg_h   = s * 0.28

    head_cy = cy - s * 0.38
    body_top = head_cy + head_r
    body_bot = body_top + body_h
    arm_y    = body_top + body_h * 0.20

    d = (
        f"M {cx:.2f},{head_cy - head_r:.2f}"
        f" C {cx + head_r * 0.7:.2f},{head_cy - head_r * 0.7:.2f}"
        f" {cx + head_r:.2f},{head_cy - head_r * 0.3:.2f} {cx + head_r:.2f},{head_cy:.2f}"
        f" C {cx + head_r:.2f},{head_cy + head_r * 0.7:.2f}"
        f" {cx + head_r * 0.5:.2f},{body_top:.2f} {cx + body_w / 2:.2f},{body_top:.2f}"
        f" L {cx + arm_w:.2f},{arm_y:.2f}"
        f" L {cx + arm_w:.2f},{arm_y + arm_h:.2f}"
        f" L {cx + body_w / 2:.2f},{body_top + body_h * 0.45:.2f}"
        f" L {cx + body_w / 2:.2f},{body_bot:.2f}"
        f" L {cx + leg_w:.2f},{body_bot:.2f}"
        f" L {cx + leg_w:.2f},{body_bot + leg_h:.2f}"
        f" L {cx - leg_w:.2f},{body_bot + leg_h:.2f}"
        f" L {cx - leg_w:.2f},{body_bot:.2f}"
        f" L {cx - body_w / 2:.2f},{body_bot:.2f}"
        f" L {cx - body_w / 2:.2f},{body_top + body_h * 0.45:.2f}"
        f" L {cx - arm_w:.2f},{arm_y + arm_h:.2f}"
        f" L {cx - arm_w:.2f},{arm_y:.2f}"
        f" L {cx - body_w / 2:.2f},{body_top:.2f}"
        f" C {cx - head_r * 0.5:.2f},{body_top:.2f}"
        f" {cx - head_r:.2f},{head_cy + head_r * 0.7:.2f} {cx - head_r:.2f},{head_cy:.2f}"
        f" C {cx - head_r:.2f},{head_cy - head_r * 0.3:.2f}"
        f" {cx - head_r * 0.7:.2f},{head_cy - head_r * 0.7:.2f} {cx:.2f},{head_cy - head_r:.2f}"
        " Z"
    )
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


# ── S2.5: nowe kształty ───────────────────────────────────────────────────────

def _path_cat(cx: float, cy: float, s: float) -> str:
    """Głowa kota z dwoma trójkątnymi uszami."""
    r = s * 0.40
    k = 0.55
    ew = s * 0.12
    eh = s * 0.20
    ey = cy - r * 0.72

    # buduj ścieżkę: dolna półokrąg, prawa strona w górę do ucha, ucho, przez środek, lewe ucho, lewa strona
    d = (
        # Start: bottom of circle
        f"M {cx:.2f},{cy + r:.2f}"
        # bezier: bottom -> right
        f" C {cx + r*k:.2f},{cy + r:.2f} {cx + r:.2f},{cy + r*k:.2f} {cx + r:.2f},{cy:.2f}"
        # bezier: right -> where ear meets head (right ear base right)
        f" C {cx + r:.2f},{ey:.2f} {cx + r*0.7:.2f},{ey:.2f} {cx + ew:.2f},{ey:.2f}"
        # right ear: up to tip and back
        f" L {cx + ew + ew:.2f},{ey - eh:.2f}"
        f" L {cx - ew + ew*2:.2f},{ey:.2f}"
        # across top between ears
        f" L {cx - ew:.2f},{ey:.2f}"
        # left ear
        f" L {cx - ew - ew:.2f},{ey - eh:.2f}"
        f" L {cx - ew*2:.2f},{ey:.2f}"
        # bezier: left ear base -> left side -> bottom
        f" C {cx - r*0.7:.2f},{ey:.2f} {cx - r:.2f},{ey:.2f} {cx - r:.2f},{cy:.2f}"
        f" C {cx - r:.2f},{cy + r*k:.2f} {cx - r*k:.2f},{cy + r:.2f} {cx:.2f},{cy + r:.2f}"
        " Z"
    )
    return d


def _path_dog(cx: float, cy: float, s: float) -> str:
    """Okrągła głowa psa z opadającymi uszami po bokach."""
    r = s * 0.33
    k = 0.55
    ew = s * 0.16
    ed = s * 0.40
    top_y = cy - r

    # head circle approximation + floppy ears
    d = (
        # Start: top of head
        f"M {cx:.2f},{top_y:.2f}"
        # top right arc
        f" C {cx + r*k:.2f},{top_y:.2f} {cx + r:.2f},{cy - r*k:.2f} {cx + r:.2f},{cy:.2f}"
        # transition to right ear (floppy, hangs down)
        f" L {cx + r + ew:.2f},{cy:.2f}"
        f" C {cx + r + ew:.2f},{cy + ed*0.6:.2f} {cx + r:.2f},{cy + ed:.2f} {cx + r*0.7:.2f},{cy + ed:.2f}"
        f" C {cx + r*0.3:.2f},{cy + ed:.2f} {cx + r*0.3:.2f},{cy + r*k:.2f} {cx + r*0.3:.2f},{cy + r:.2f}"
        # bottom of head
        f" C {cx + r*0.3:.2f},{cy + r:.2f} {cx - r*0.3:.2f},{cy + r:.2f} {cx - r*0.3:.2f},{cy + r:.2f}"
        f" C {cx - r*0.3:.2f},{cy + r*k:.2f} {cx - r*0.3:.2f},{cy + ed:.2f} {cx - r*0.7:.2f},{cy + ed:.2f}"
        # left ear
        f" C {cx - r:.2f},{cy + ed:.2f} {cx - r - ew:.2f},{cy + ed*0.6:.2f} {cx - r - ew:.2f},{cy:.2f}"
        f" L {cx - r:.2f},{cy:.2f}"
        # left arc back to top
        f" C {cx - r:.2f},{cy - r*k:.2f} {cx - r*k:.2f},{top_y:.2f} {cx:.2f},{top_y:.2f}"
        " Z"
    )
    return d


def _path_rabbit(cx: float, cy: float, s: float) -> str:
    """Okrągłe ciało z dwoma wysokimi cienkimi uszami."""
    br = s * 0.30
    k = 0.55
    ew = s * 0.08
    eh = s * 0.40
    off = s * 0.12
    body_top = cy - br

    d = (
        # Start: bottom of body
        f"M {cx:.2f},{cy + br:.2f}"
        # right body arc going up to right ear base
        f" C {cx + br*k:.2f},{cy + br:.2f} {cx + br:.2f},{cy + br*k:.2f} {cx + br:.2f},{cy:.2f}"
        f" C {cx + br:.2f},{cy - br*k:.2f} {cx + br*k:.2f},{body_top:.2f} {cx + off + ew:.2f},{body_top:.2f}"
        # right ear going up
        f" C {cx + off + ew:.2f},{body_top - eh*0.3:.2f} {cx + off + ew:.2f},{body_top - eh:.2f} {cx + off:.2f},{body_top - eh:.2f}"
        f" C {cx + off - ew:.2f},{body_top - eh:.2f} {cx + off - ew:.2f},{body_top - eh*0.3:.2f} {cx + off - ew:.2f},{body_top:.2f}"
        # across top to left ear
        f" L {cx - off + ew:.2f},{body_top:.2f}"
        # left ear
        f" C {cx - off + ew:.2f},{body_top - eh*0.3:.2f} {cx - off + ew:.2f},{body_top - eh:.2f} {cx - off:.2f},{body_top - eh:.2f}"
        f" C {cx - off - ew:.2f},{body_top - eh:.2f} {cx - off - ew:.2f},{body_top - eh*0.3:.2f} {cx - off - ew:.2f},{body_top:.2f}"
        # left body arc
        f" C {cx - br*k:.2f},{body_top:.2f} {cx - br:.2f},{cy - br*k:.2f} {cx - br:.2f},{cy:.2f}"
        f" C {cx - br:.2f},{cy + br*k:.2f} {cx - br*k:.2f},{cy + br:.2f} {cx:.2f},{cy + br:.2f}"
        " Z"
    )
    return d


def _path_hen(cx: float, cy: float, s: float) -> str:
    """Okrągłe ciało z trójkątnym dziobem po prawej stronie."""
    r = s * 0.38
    k = 0.55
    beak_w = s * 0.14
    beak_h = s * 0.10
    beak_y = cy

    d = (
        f"M {cx:.2f},{cy - r:.2f}"
        # top right arc
        f" C {cx + r*k:.2f},{cy - r:.2f} {cx + r:.2f},{cy - r*k:.2f} {cx + r:.2f},{beak_y - beak_h:.2f}"
        # beak protrusion
        f" L {cx + r + beak_w:.2f},{beak_y:.2f}"
        f" L {cx + r:.2f},{beak_y + beak_h:.2f}"
        # bottom right arc
        f" C {cx + r:.2f},{cy + r*k:.2f} {cx + r*k:.2f},{cy + r:.2f} {cx:.2f},{cy + r:.2f}"
        # bottom left arc
        f" C {cx - r*k:.2f},{cy + r:.2f} {cx - r:.2f},{cy + r*k:.2f} {cx - r:.2f},{cy:.2f}"
        # top left arc
        f" C {cx - r:.2f},{cy - r*k:.2f} {cx - r*k:.2f},{cy - r:.2f} {cx:.2f},{cy - r:.2f}"
        " Z"
    )
    return d


def _path_bear(cx: float, cy: float, s: float) -> str:
    """Okrągła głowa z dwoma małymi semicirkularnymi uszami na górze."""
    r = s * 0.38
    k = 0.55
    er = s * 0.11
    # ear centers
    el_cx = cx - r * 0.55
    er_cx = cx + r * 0.55
    ear_cy = cy - r * 0.85

    # We'll build: circle from bottom, at top include two ear bumps
    d = (
        # Start at bottom
        f"M {cx:.2f},{cy + r:.2f}"
        # right side up
        f" C {cx + r*k:.2f},{cy + r:.2f} {cx + r:.2f},{cy + r*k:.2f} {cx + r:.2f},{cy:.2f}"
        f" C {cx + r:.2f},{cy - r*k:.2f} {cx + r*k:.2f},{cy - r:.2f} {er_cx + er:.2f},{ear_cy:.2f}"
        # right ear semicircle bump (going over the top)
        f" C {er_cx + er:.2f},{ear_cy - er*k:.2f} {er_cx + er*k:.2f},{ear_cy - er:.2f} {er_cx:.2f},{ear_cy - er:.2f}"
        f" C {er_cx - er*k:.2f},{ear_cy - er:.2f} {er_cx - er:.2f},{ear_cy - er*k:.2f} {er_cx - er:.2f},{ear_cy:.2f}"
        # top middle between ears
        f" L {el_cx + er:.2f},{ear_cy:.2f}"
        # left ear semicircle bump
        f" C {el_cx + er:.2f},{ear_cy - er*k:.2f} {el_cx + er*k:.2f},{ear_cy - er:.2f} {el_cx:.2f},{ear_cy - er:.2f}"
        f" C {el_cx - er*k:.2f},{ear_cy - er:.2f} {el_cx - er:.2f},{ear_cy - er*k:.2f} {el_cx - er:.2f},{ear_cy:.2f}"
        # left side down
        f" C {cx - r*k:.2f},{cy - r:.2f} {cx - r:.2f},{cy - r*k:.2f} {cx - r:.2f},{cy:.2f}"
        f" C {cx - r:.2f},{cy + r*k:.2f} {cx - r*k:.2f},{cy + r:.2f} {cx:.2f},{cy + r:.2f}"
        " Z"
    )
    return d


def _path_owl(cx: float, cy: float, s: float) -> str:
    """Owalne ciało z dwoma spiczastymi pęczkami piór na górze."""
    rx = s * 0.34
    ry = s * 0.44
    k = 0.55
    tw = s * 0.10
    th = s * 0.18
    tuft_y = cy - ry

    d = (
        # Start at bottom
        f"M {cx:.2f},{cy + ry:.2f}"
        # right side up (ellipse approximation)
        f" C {cx + rx*k:.2f},{cy + ry:.2f} {cx + rx:.2f},{cy + ry*k:.2f} {cx + rx:.2f},{cy:.2f}"
        f" C {cx + rx:.2f},{cy - ry*k:.2f} {cx + rx*k:.2f},{tuft_y:.2f} {cx + tw + tw:.2f},{tuft_y:.2f}"
        # right tuft (triangular point upward)
        f" L {cx + tw:.2f},{tuft_y - th:.2f}"
        f" L {cx:.2f},{tuft_y:.2f}"
        # left tuft
        f" L {cx - tw:.2f},{tuft_y - th:.2f}"
        f" L {cx - tw - tw:.2f},{tuft_y:.2f}"
        # left side down
        f" C {cx - rx*k:.2f},{tuft_y:.2f} {cx - rx:.2f},{cy - ry*k:.2f} {cx - rx:.2f},{cy:.2f}"
        f" C {cx - rx:.2f},{cy + ry*k:.2f} {cx - rx*k:.2f},{cy + ry:.2f} {cx:.2f},{cy + ry:.2f}"
        " Z"
    )
    return d


def _path_llama(cx: float, cy: float, s: float) -> str:
    """Mała głowa na długiej szyi na szerokim ciele."""
    bw = s * 0.42
    bh = s * 0.28
    nw = s * 0.12
    nh = s * 0.26
    hw = s * 0.20
    hh = s * 0.16

    body_cy = cy + s * 0.18
    body_top = body_cy - bh / 2
    body_bot = body_cy + bh / 2
    neck_bot = body_top
    neck_top = neck_bot - nh
    head_top = neck_top - hh

    d = (
        # Start: bottom left of body
        f"M {cx - bw/2:.2f},{body_bot:.2f}"
        f" L {cx + bw/2:.2f},{body_bot:.2f}"
        f" L {cx + bw/2:.2f},{body_top:.2f}"
        # right side: body to neck
        f" L {cx + nw/2:.2f},{neck_bot:.2f}"
        f" L {cx + nw/2:.2f},{neck_top:.2f}"
        # head right side
        f" L {cx + hw/2:.2f},{neck_top:.2f}"
        f" L {cx + hw/2:.2f},{head_top:.2f}"
        f" L {cx - hw/2:.2f},{head_top:.2f}"
        f" L {cx - hw/2:.2f},{neck_top:.2f}"
        # neck left side
        f" L {cx - nw/2:.2f},{neck_top:.2f}"
        f" L {cx - nw/2:.2f},{neck_bot:.2f}"
        f" L {cx - bw/2:.2f},{body_top:.2f}"
        " Z"
    )
    return d


def _path_fish(cx: float, cy: float, s: float) -> str:
    """Owalny tułów z trójkątną płetwą ogonową po lewej stronie."""
    # body center slightly right
    bcx = cx + s * 0.06
    brx = s * 0.32
    bry = s * 0.22
    k = 0.55
    # tail on the left
    tail_x = bcx - brx
    tail_w = s * 0.18
    tail_h = s * 0.34

    d = (
        # Start: top of body (rightmost)
        f"M {bcx:.2f},{cy - bry:.2f}"
        # right arc
        f" C {bcx + brx*k:.2f},{cy - bry:.2f} {bcx + brx:.2f},{cy - bry*k:.2f} {bcx + brx:.2f},{cy:.2f}"
        f" C {bcx + brx:.2f},{cy + bry*k:.2f} {bcx + brx*k:.2f},{cy + bry:.2f} {bcx:.2f},{cy + bry:.2f}"
        # left arc to tail junction bottom
        f" C {bcx - brx*k:.2f},{cy + bry:.2f} {tail_x:.2f},{cy + bry*k:.2f} {tail_x:.2f},{cy + tail_h/2:.2f}"
        # tail bottom point (to the left)
        f" L {tail_x - tail_w:.2f},{cy:.2f}"
        # tail top
        f" L {tail_x:.2f},{cy - tail_h/2:.2f}"
        # back up left side of body
        f" C {tail_x:.2f},{cy - bry*k:.2f} {bcx - brx*k:.2f},{cy - bry:.2f} {bcx:.2f},{cy - bry:.2f}"
        " Z"
    )
    return d


def _path_bird(cx: float, cy: float, s: float) -> str:
    """Kroplowate ciało (szersze z prawej, spiczaste z lewej) z małym dziobem po prawej."""
    w = s * 0.46
    h = s * 0.36
    beak_h = s * 0.07
    beak_w = s * 0.10

    # teardrop: rounded right, pointed left
    d = (
        f"M {cx - w/2:.2f},{cy:.2f}"
        # top curve: left tip -> top -> right
        f" C {cx - w/2:.2f},{cy - h/2:.2f} {cx:.2f},{cy - h/2:.2f} {cx + w*0.3:.2f},{cy - h/2:.2f}"
        f" C {cx + w*0.5:.2f},{cy - h/2:.2f} {cx + w/2:.2f},{cy - beak_h:.2f} {cx + w/2:.2f},{cy - beak_h:.2f}"
        # small beak bump on right
        f" L {cx + w/2 + beak_w:.2f},{cy:.2f}"
        f" L {cx + w/2:.2f},{cy + beak_h:.2f}"
        # bottom curve: right -> bottom -> left tip
        f" C {cx + w/2:.2f},{cy + h/2:.2f} {cx + w*0.5:.2f},{cy + h/2:.2f} {cx + w*0.3:.2f},{cy + h/2:.2f}"
        f" C {cx:.2f},{cy + h/2:.2f} {cx - w/2:.2f},{cy + h/2:.2f} {cx - w/2:.2f},{cy:.2f}"
        " Z"
    )
    return d


def _path_apple(cx: float, cy: float, s: float) -> str:
    """Okrągłe jabłko z małym wcięciem na górze i listkiem."""
    r = s * 0.38
    k = 0.55
    notch_w = s * 0.08
    notch_d = s * 0.10
    leaf_w = s * 0.14
    leaf_h = s * 0.16
    leaf_x = cx + s * 0.12
    leaf_y = cy - r - notch_d + s * 0.04

    top_y = cy - r

    d = (
        # Start: bottom
        f"M {cx:.2f},{cy + r:.2f}"
        # right side up
        f" C {cx + r*k:.2f},{cy + r:.2f} {cx + r:.2f},{cy + r*k:.2f} {cx + r:.2f},{cy:.2f}"
        f" C {cx + r:.2f},{cy - r*k:.2f} {cx + r*k:.2f},{top_y:.2f} {cx + notch_w:.2f},{top_y:.2f}"
        # notch at top center
        f" C {cx + notch_w:.2f},{top_y - notch_d:.2f} {cx - notch_w:.2f},{top_y - notch_d:.2f} {cx - notch_w:.2f},{top_y:.2f}"
        # left side down
        f" C {cx - r*k:.2f},{top_y:.2f} {cx - r:.2f},{cy - r*k:.2f} {cx - r:.2f},{cy:.2f}"
        f" C {cx - r:.2f},{cy + r*k:.2f} {cx - r*k:.2f},{cy + r:.2f} {cx:.2f},{cy + r:.2f}"
        # leaf: small oval offset to upper right (attached separately via M would be subpath)
        # Instead integrate leaf as a bump near notch right side
        " Z"
    )
    return d


def _path_cactus(cx: float, cy: float, s: float) -> str:
    """Kaktus z trzema segmentami (tułów + 2 ramiona)."""
    tw = s * 0.18  # trunk half-width
    th = s * 0.44  # trunk half-height
    aw = s * 0.20  # arm horizontal length
    ah = s * 0.16  # arm vertical height
    arm_r = s * 0.06  # arm rounding

    trunk_top = cy - th
    trunk_bot = cy + th
    # left arm at 1/3 height from top
    la_y = cy - th * 0.3
    # right arm at 1/2 height from top
    ra_y = cy - th * 0.0

    d = (
        # Start: bottom left of trunk
        f"M {cx - tw:.2f},{trunk_bot:.2f}"
        f" L {cx + tw:.2f},{trunk_bot:.2f}"
        f" L {cx + tw:.2f},{ra_y + ah:.2f}"
        # right arm: goes right, then up
        f" L {cx + tw + aw:.2f},{ra_y + ah:.2f}"
        f" L {cx + tw + aw:.2f},{ra_y:.2f}"
        f" L {cx + tw:.2f},{ra_y:.2f}"
        f" L {cx + tw:.2f},{la_y + ah:.2f}"
        # continue up trunk
        f" L {cx + tw:.2f},{trunk_top:.2f}"
        f" L {cx - tw:.2f},{trunk_top:.2f}"
        f" L {cx - tw:.2f},{la_y:.2f}"
        # left arm: goes left, then up
        f" L {cx - tw - aw:.2f},{la_y:.2f}"
        f" L {cx - tw - aw:.2f},{la_y + ah:.2f}"
        f" L {cx - tw:.2f},{la_y + ah:.2f}"
        f" L {cx - tw:.2f},{trunk_bot:.2f}"
        " Z"
    )
    return d


def _path_strawberry(cx: float, cy: float, s: float) -> str:
    """Zaokrąglony trójkąt szerszy na górze, spiczasty na dole."""
    w = s * 0.44
    h = s * 0.48
    top_y = cy - h / 2
    bot_y = cy + h / 2

    d = (
        f"M {cx:.2f},{bot_y:.2f}"
        # right side up to top
        f" C {cx + w*0.5:.2f},{cy + h*0.1:.2f} {cx + w:.2f},{cy - h*0.1:.2f} {cx + w*0.8:.2f},{top_y:.2f}"
        # top right bump
        f" C {cx + w*0.9:.2f},{top_y - h*0.1:.2f} {cx + w*0.4:.2f},{top_y - h*0.15:.2f} {cx:.2f},{top_y:.2f}"
        # top left bump
        f" C {cx - w*0.4:.2f},{top_y - h*0.15:.2f} {cx - w*0.9:.2f},{top_y - h*0.1:.2f} {cx - w*0.8:.2f},{top_y:.2f}"
        # left side down to tip
        f" C {cx - w:.2f},{cy - h*0.1:.2f} {cx - w*0.5:.2f},{cy + h*0.1:.2f} {cx:.2f},{bot_y:.2f}"
        " Z"
    )
    return d


def _path_tulip(cx: float, cy: float, s: float) -> str:
    """Kielich tulipana z trzema zaokrąglonymi płatkami i krótką łodygą."""
    cup_h = s * 0.30
    stem_h = s * 0.16
    stem_w = s * 0.12
    petal_w = s * 0.42

    cup_top = cy - cup_h / 2 - stem_h / 2
    cup_bot = cup_top + cup_h
    stem_top = cup_bot
    stem_bot = stem_top + stem_h

    d = (
        # stem
        f"M {cx - stem_w/2:.2f},{stem_bot:.2f}"
        f" L {cx + stem_w/2:.2f},{stem_bot:.2f}"
        f" L {cx + stem_w/2:.2f},{stem_top:.2f}"
        # right petal of cup
        f" C {cx + petal_w*0.6:.2f},{cup_bot:.2f} {cx + petal_w/2:.2f},{cup_bot - cup_h*0.3:.2f} {cx + petal_w*0.3:.2f},{cup_top:.2f}"
        # middle petal (center)
        f" C {cx + petal_w*0.15:.2f},{cup_top - cup_h*0.3:.2f} {cx - petal_w*0.15:.2f},{cup_top - cup_h*0.3:.2f} {cx - petal_w*0.3:.2f},{cup_top:.2f}"
        # left petal
        f" C {cx - petal_w/2:.2f},{cup_bot - cup_h*0.3:.2f} {cx - petal_w*0.6:.2f},{cup_bot:.2f} {cx - stem_w/2:.2f},{stem_top:.2f}"
        " Z"
    )
    return d


def _path_easter_egg(cx: float, cy: float, s: float) -> str:
    """Prosta owalna jajeczko."""
    rx = s * 0.30
    ry = s * 0.42
    k = 0.55

    d = (
        f"M {cx:.2f},{cy - ry:.2f}"
        f" C {cx + rx*k:.2f},{cy - ry:.2f} {cx + rx:.2f},{cy - ry*k:.2f} {cx + rx:.2f},{cy:.2f}"
        f" C {cx + rx:.2f},{cy + ry*k:.2f} {cx + rx*k:.2f},{cy + ry:.2f} {cx:.2f},{cy + ry:.2f}"
        f" C {cx - rx*k:.2f},{cy + ry:.2f} {cx - rx:.2f},{cy + ry*k:.2f} {cx - rx:.2f},{cy:.2f}"
        f" C {cx - rx:.2f},{cy - ry*k:.2f} {cx - rx*k:.2f},{cy - ry:.2f} {cx:.2f},{cy - ry:.2f}"
        " Z"
    )
    return d


def _path_crown(cx: float, cy: float, s: float) -> str:
    """Płaska podstawa z 5 trójkątnymi punktami na górze."""
    base_hw = s * 0.44
    base_h = s * 0.18
    point_h = s * 0.24
    n_points = 5

    base_top = cy - base_h / 2
    base_bot = cy + base_h / 2 + point_h / 2

    # evenly space 5 points across the top
    x_positions = [cx - base_hw + (2 * base_hw / (n_points - 1)) * i for i in range(n_points)]

    pts = []
    # build top profile: for each gap between points, valley; for each point, tip
    # start from bottom left
    d = f"M {cx - base_hw:.2f},{base_bot:.2f}"
    d += f" L {cx + base_hw:.2f},{base_bot:.2f}"
    d += f" L {cx + base_hw:.2f},{base_top:.2f}"

    # 5 triangular points from right to left
    valley_xs = [cx + base_hw]  # between points
    for i in range(n_points - 1):
        valley_xs.append((x_positions[i] + x_positions[i + 1]) / 2)
    valley_xs.append(cx - base_hw)

    for i in range(n_points - 1, -1, -1):
        tip_x = x_positions[i]
        tip_y = base_top - point_h
        d += f" L {tip_x:.2f},{tip_y:.2f}"
        d += f" L {valley_xs[i]:.2f},{base_top:.2f}"

    d += " Z"
    return d


def _path_cookie(cx: float, cy: float, s: float) -> str:
    """Scalloped circle with 12 rounded bumps (like a cookie/biscuit)."""
    n = 12
    r_outer = s * 0.46
    r_inner = s * 0.34

    pts: list[tuple[float, float]] = []
    for i in range(n * 2):
        angle = math.radians(i * 180 / n - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    first_mid_x = (pts[-1][0] + pts[0][0]) / 2
    first_mid_y = (pts[-1][1] + pts[0][1]) / 2
    d = f"M {first_mid_x:.2f},{first_mid_y:.2f}"
    for i in range(len(pts)):
        ctrl = pts[i]
        nxt  = pts[(i + 1) % len(pts)]
        mid_x = (ctrl[0] + nxt[0]) / 2
        mid_y = (ctrl[1] + nxt[1]) / 2
        d += f" Q {ctrl[0]:.2f},{ctrl[1]:.2f} {mid_x:.2f},{mid_y:.2f}"
    d += " Z"
    return d


SHAPE_BUILDERS = {
    "mountain":       _path_mountain,
    "heart":          _path_heart,
    "star":           _path_star,
    "moon":           _path_moon,
    "floral":         _path_floral,
    "leaf":           _path_leaf,
    "butterfly":      _path_butterfly,
    "mushroom":       _path_mushroom,
    "hexagon":        _path_hexagon,
    "sun":            _path_sun,
    "pumpkin":        _path_pumpkin,
    "christmas_tree": _path_christmas_tree,
    "snowflake":      _path_snowflake,
    "gingerbread":    _path_gingerbread,
    "rounded_rect":   _path_rounded_rect,
    # S2.5 new shapes
    "cat":            _path_cat,
    "dog":            _path_dog,
    "rabbit":         _path_rabbit,
    "hen":            _path_hen,
    "bear":           _path_bear,
    "owl":            _path_owl,
    "llama":          _path_llama,
    "fish":           _path_fish,
    "bird":           _path_bird,
    "apple":          _path_apple,
    "cactus":         _path_cactus,
    "strawberry":     _path_strawberry,
    "tulip":          _path_tulip,
    "easter_egg":     _path_easter_egg,
    "crown":          _path_crown,
    "cookie":         _path_cookie,
}


# ── S2.4: stamp elements ──────────────────────────────────────────────────────

def _stamp_elements_mock(shape_key: str, cx: float, cy: float, size_mm: float) -> list[str]:
    """
    Generuje elementy SVG dla warstwy stamp (wewnętrzne detale embossera).

    Returns:
        Lista stringów SVG element (path, circle, etc.)
    """
    elements: list[str] = []

    # 1. Stamp outline: mniejszy kształt (s * 0.38 zamiast s * 0.46 używanego przez outer)
    builder = SHAPE_BUILDERS.get(shape_key, _path_rounded_rect)
    s_inner = size_mm * 0.38
    stamp_d = builder(cx, cy, s_inner)
    elements.append(
        f'<path id="stamp_outline" d="{stamp_d}" fill="none" stroke="#666666" stroke-width="0.8"/>'
    )

    # 2. Creature shapes: oczy + uśmiech
    if shape_key in CREATURE_SHAPES:
        eye_y = cy - size_mm * 0.08
        eye_r = max(2.5, size_mm * 0.04)
        eye_off = size_mm * 0.10
        sm_y = cy + size_mm * 0.05
        sw = size_mm * 0.12

        elements.append(
            f'<circle id="eye_l" cx="{cx - eye_off:.2f}" cy="{eye_y:.2f}" r="{eye_r:.2f}" fill="#333333"/>'
        )
        elements.append(
            f'<circle id="eye_r" cx="{cx + eye_off:.2f}" cy="{eye_y:.2f}" r="{eye_r:.2f}" fill="#333333"/>'
        )
        elements.append(
            f'<path id="smile" d="M {cx - sw:.2f},{sm_y:.2f} Q {cx:.2f},{sm_y + sw * 0.6:.2f} {cx + sw:.2f},{sm_y:.2f}" '
            f'fill="none" stroke="#333333" stroke-width="1.0"/>'
        )

    # 3. Plant/food shapes: 3 dekoracyjne kropki
    elif shape_key in PLANT_FOOD_SHAPES:
        dot_r = max(1.5, size_mm * 0.025)
        for offset in (-size_mm * 0.12, 0.0, size_mm * 0.12):
            elements.append(
                f'<circle cx="{cx + offset:.2f}" cy="{cy:.2f}" r="{dot_r:.2f}" fill="#999999"/>'
            )

    return elements


# ── S2.2: nowy _write_svg (raw XML) ──────────────────────────────────────────

def _write_svg(
    path_d: str,
    out_path: Path,
    size_mm: float,
    product_type: str,
    topic: str,
    size: str,
    shape: str,
    stamp_elements: list[str] | None = None,
) -> dict:
    """Zapisuje SVG z gotową ścieżką path_d — format compound (outer + stamp layers)."""
    stamp_elements_joined = "\n    ".join(stamp_elements) if stamp_elements else ""

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{size_mm}mm" height="{size_mm}mm"
     viewBox="0 0 {size_mm} {size_mm}">
  <rect width="{size_mm}mm" height="{size_mm}mm" fill="white"/>
  <!-- LAYER 1: outer — zewnętrzna sylwetka cuttera -->
  <g id="outer">
    <path id="outer_contour" d="{path_d}" fill="none" stroke="#000000" stroke-width="1.2"/>
  </g>
  <!-- LAYER 2: stamp — wewnętrzne detale embossera -->
  <g id="stamp">
    {stamp_elements_joined}
  </g>
</svg>"""

    out_path.write_text(xml, encoding="utf-8")

    return {
        "size": size,
        "path": str(out_path),
        "width_mm": size_mm,
        "height_mm": size_mm,
        "shape": shape,
        "has_stamp": bool(stamp_elements),
    }


def _make_svg_dalle_potrace(
    topic: str,
    product_type: str,
    size: str,
    out_path: Path,
) -> dict:
    """
    Pipeline: DALL-E 3 PNG → ImageMagick threshold → potrace → SVG cleanup.
    Fallback do _make_svg_real jeśli któryś krok zawiedzie.
    """
    import openai as _openai

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set — falling back to real SVG")
        return _make_svg_real(topic, product_type, size, out_path)

    size_mm = SIZE_MM.get(size.upper(), 75.0)

    # ── 1. DALL-E 3: generuj PNG ─────────────────────────────────────
    dalle_prompt = DALLE_PROMPTS.get(topic.lower(), _DALLE_DEFAULT.format(topic=topic))

    try:
        client_oai = _openai.OpenAI(api_key=api_key)
        log.info("DALL-E 3: generating image for '%s'", topic)
        response = client_oai.images.generate(
            model="dall-e-3",
            prompt=dalle_prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url
    except Exception as e:
        log.warning("DALL-E 3 failed (%s) — falling back to real SVG", e)
        return _make_svg_real(topic, product_type, size, out_path)

    # Zapisz raw PNG do source/ obok SVG (przed przetwarzaniem)
    raw_png_dest = out_path.parent / f"{out_path.stem}_dalle_raw.png"
    try:
        urllib.request.urlretrieve(image_url, raw_png_dest)
    except Exception as e:
        log.warning("PNG download failed (%s) — falling back to real SVG", e)
        return _make_svg_real(topic, product_type, size, out_path)
    png_path = raw_png_dest

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bmp_path = tmp_path / "threshold.bmp"
        svg_raw  = tmp_path / "traced.svg"

        # ── 3. ImageMagick: threshold → czarno-biały BMP ────────────
        try:
            subprocess.run(
                [
                    "convert", str(png_path),
                    "-colorspace", "Gray",
                    "-threshold", "50%",
                    "-negate",
                    "-type", "Bilevel",
                    str(bmp_path),
                ],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            log.warning("ImageMagick failed (%s) — falling back to real SVG", e.stderr)
            return _make_svg_real(topic, product_type, size, out_path)

        # ── 4. potrace: BMP → SVG ────────────────────────────────────
        try:
            subprocess.run(
                [
                    "potrace", str(bmp_path),
                    "--svg",
                    "--output", str(svg_raw),
                    "--turdsize", "80",
                    "--alphamax", "1.5",
                    "--opttolerance", "0.5",
                ],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            log.warning("potrace failed (%s) — falling back to real SVG", e.stderr)
            return _make_svg_real(topic, product_type, size, out_path)

        # ── 5. Wyciągnij ścieżki z SVG potrace ──────────────────────
        raw_svg = svg_raw.read_text(encoding="utf-8")

        # potrace generuje <g transform="translate(0,H) scale(0.1,-0.1)">
        # Wyciągnij wszystkie ścieżki
        all_ds = re.findall(r'<path[^>]+\bd="([^"]+)"', raw_svg, re.DOTALL)
        if not all_ds:
            log.warning("potrace SVG: no paths found — falling back")
            return _make_svg_real(topic, product_type, size, out_path)

        # Usuń pierwszą ścieżkę jeśli to ramka tła
        # (zaczyna się od M0 lub M2 i obejmuje cały canvas)
        paths_to_use = all_ds
        if len(all_ds) > 1:
            first = all_ds[0].strip()
            if re.match(r'^M\s*\d{1,3}\s+\d{4}', first):
                paths_to_use = all_ds[1:]

        path_d_raw = " ".join(paths_to_use)

        import re as _re2
        segments = _re2.findall(r'M[^M]+', path_d_raw)
        if len(segments) > 1:
            # Usuń ramkę canvas potrace (segment zaczyna się od M0 = lewa/dolna krawędź)
            segments = [s for s in segments if not _re2.match(r'^M\s*0[\s,]', s.strip())]
            if not segments:
                log.warning("potrace: wszystkie segmenty odfiltrowane — fallback")
                return _make_svg_real(topic, product_type, size, out_path)
            # Zachowaj segmenty >= 10% długości najdłuższego
            segments_sorted = sorted(segments, key=len, reverse=True)
            threshold = len(segments_sorted[0]) * 0.10
            main_segs = [s for s in segments_sorted if len(s) >= threshold]
            path_d_raw = " ".join(main_segs)
            log.info("subpaths: %d → %d (po usunięciu ramki + próg 10%%)",
                     len(segments), len(main_segs))

    # potrace viewBox jest w jednostkach pt×10 (transform scale 0.1)
    # rzeczywisty rozmiar = viewBox / 10
    vb = re.search(r'viewBox=["\']([^"\']+)["\']', raw_svg)
    if vb:
        parts = vb.group(1).split()
        try:
            src_w = float(parts[2]) * 10.0
            src_h = float(parts[3]) * 10.0
        except (IndexError, ValueError):
            src_w = src_h = 1024.0
    else:
        src_w = src_h = 1024.0

    scale_x = (size_mm * 0.88) / src_w
    scale_y = (size_mm * 0.88) / src_h
    offset  = size_mm * 0.06

    def _scale_path(d: str, sx: float, sy: float) -> str:
        """Skaluje współrzędne SVG path zachowując komendy."""
        import re as _re
        tokens = _re.split(r'([MLCQSZHVmlcqszhv])', d)
        result = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            if tok in 'MLCQSZHVmlcqszhv':
                result.append(tok)
            else:
                nums = _re.findall(r'-?\d+\.?\d*(?:e[+-]?\d+)?', tok)
                scaled = []
                for i, n in enumerate(nums):
                    v = float(n)
                    scaled.append(f'{v * sx:.3f}' if i % 2 == 0 else f'{v * sy:.3f}')
                result.append(' '.join(scaled))
        return ' '.join(result)

    path_d = _scale_path(path_d_raw, scale_x, scale_y)

    # ── 7. Zapisz finalny SVG z transformem korygującym y-flip ──────
    # Walidacja z 3× marginesem — SVG viewBox przytnie nadmiar przy renderowaniu
    ok, reason = _validate_path(path_d, size_mm * 3)
    if not ok:
        log.warning("potrace validation failed (%s) — falling back", reason)
        return _make_svg_real(topic, product_type, size, out_path)

    stroke_w = 1.5  # mm — bezpośrednio w przestrzeni viewBox po scale(1,-1)

    svg_out = f"""<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{size_mm}mm" height="{size_mm}mm"
     viewBox="0 0 {size_mm} {size_mm}">
  <rect width="{size_mm}mm" height="{size_mm}mm" fill="white"/>
  <!-- DALL-E 3 + potrace | topic: {topic} | size: {size} -->
  <g id="outer"
     transform="translate(0,{size_mm:.2f}) scale(1,-1)">
    <path id="outer_contour"
          d="{path_d}"
          fill="white"
          fill-rule="evenodd"
          stroke="#000000"
          stroke-width="{stroke_w:.3f}"
          stroke-linecap="round"
          stroke-linejoin="round"/>
  </g>
  <g id="stamp"/>
</svg>"""
    out_path.write_text(svg_out, encoding="utf-8")
    log.info("DALL-E+potrace SVG OK: %s (%.0fmm, %d paths)", out_path, size_mm, len(paths_to_use))
    return {
        "size": size, "path": str(out_path),
        "width_mm": size_mm, "height_mm": size_mm,
        "shape": "dalle_potrace", "has_stamp": False,
    }


def _make_svg_mock(
    topic: str,
    product_type: str,
    size: str,
    out_path: Path,
) -> dict:
    """Generuje placeholder SVG z kształtem bazującym na temacie."""
    size_mm   = SIZE_MM.get(size.upper(), 75.0)
    shape_key = _detect_shape(topic)
    builder   = SHAPE_BUILDERS[shape_key]
    cx, cy    = size_mm / 2, size_mm / 2
    path_d    = builder(cx, cy, size_mm * 0.46)

    # S2.4: generuj stamp elements
    stamp_elements = _stamp_elements_mock(shape_key, cx, cy, size_mm)

    log.info("Mock SVG: %s (%.0fmm, shape=%s)", out_path, size_mm, shape_key)
    return _write_svg(path_d, out_path, size_mm, product_type, topic, size, shape_key, stamp_elements)


SHAPE_HINTS: dict[str, str] = {
    "floral wreath": (
        "A circular wreath: 6 evenly-spaced 5-petal flowers around a circle, "
        "small leaves between flowers. Draw outer ring first, then each flower. "
        "Multiple subpaths allowed — one M per element."
    ),
    "mountain climbing": (
        "A mountain silhouette: large central triangle peak with rounded top, "
        "smaller peak on left, jagged rocky base. Single closed path."
    ),
    "butterflies": (
        "A butterfly: two large rounded upper wings, two smaller lower wings, "
        "oval body in center. Symmetrical left-right. Multiple subpaths OK."
    ),
    "celestial moon stars": (
        "A crescent moon facing right with 3 small 5-point stars around it. "
        "Moon = thick crescent shape. Multiple subpaths for moon + each star."
    ),
    "cottagecore mushrooms": (
        "A single mushroom: wide rounded dome cap, short thick stem, "
        "2-3 circular spots on cap. Chubby kawaii proportions. Multiple subpaths."
    ),
    "hearts romantic": (
        "A classic heart shape: two rounded bumps at top meeting at a point below. "
        "Chubby kawaii proportions, very smooth curves. Single closed path."
    ),
    "geometric abstract": (
        "A 6-pointed star with rounded tips, inner hexagon outline. "
        "Two overlapping triangles forming Star of David shape. Multiple subpaths."
    ),
    "botanical leaves": (
        "A single leaf: oval shape tapering to point, central midrib line, "
        "4 curved side veins. Slightly asymmetric natural look. Multiple subpaths."
    ),
    "christmas snowflake": (
        "A 6-arm snowflake: 6 identical arms radiating from center, "
        "each arm has 2 small branches. Perfectly symmetrical. Multiple subpaths."
    ),
    "halloween ghost": (
        "A cute ghost: rounded dome top, wavy bottom edge with 3 bumps, "
        "two oval eyes, small O mouth. Single flowing closed path."
    ),
    "halloween pumpkin": (
        "A pumpkin: round body with 5 vertical segments, short stem on top, "
        "small leaf. Triangle eyes and jagged smile. Multiple subpaths."
    ),
    "easter bunny": (
        "A bunny head: round face, two tall oval ears, small nose, "
        "whisker dots. Chubby kawaii style. Multiple subpaths."
    ),
    "easter egg": (
        "An egg shape: oval taller than wide, horizontal zigzag band across middle, "
        "small dots above and below band. Multiple subpaths."
    ),
    "gingerbread house": (
        "A house silhouette: square base with triangular roof, "
        "centered door rectangle, two window squares. Multiple subpaths."
    ),
}

DALLE_PROMPTS: dict[str, str] = {
    "floral wreath": (
        "Black silhouette floral wreath on pure white background. "
        "NO circle, NO oval, NO border, NO frame, NO background shape. "
        "Only black flowers and leaves on flat white. "
        "Solid black fills only. No gradients, no shading, no outlines. "
        "Flat rubber stamp style. Maximum contrast."
    ),
    "mountain climbing": (
        "A cute kawaii mountain, flat 2D design, pure white background, "
        "thick bold BLACK outline only, single mountain peak with rounded top, "
        "small snow cap, tiny kawaii face with dot eyes, small pine trees on sides, "
        "zero fill zero color zero shading, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "butterflies": (
        "A cute kawaii butterfly, flat 2D design, pure white background, "
        "thick bold BLACK outline only, perfectly symmetrical, "
        "large rounded upper wings, smaller lower wings, oval body, "
        "simple antennae, zero fill zero color, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "celestial moon stars": (
        "A cute kawaii crescent moon with stars, flat 2D design, "
        "pure white background, thick bold BLACK outline only, "
        "thick crescent moon shape with kawaii dot eyes, "
        "3 five-pointed stars of different sizes around it, "
        "zero fill zero color zero shading, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "cottagecore mushrooms": (
        "A cute kawaii mushroom, flat 2D design, pure white background, "
        "thick bold BLACK outline only, wide rounded dome cap, "
        "short thick stem, 3 circular spots on cap, kawaii dot eyes on stem, "
        "zero fill zero color, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "hearts romantic": (
        "A cute kawaii heart shape, flat 2D design, pure white background, "
        "thick bold BLACK outline only, classic heart with very chubby rounded bumps, "
        "zero fill zero color zero shading, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "geometric abstract": (
        "A cute geometric star, flat 2D design, pure white background, "
        "thick bold BLACK outline only, 6-pointed star with rounded tips, "
        "inner hexagon decorative outline, zero fill zero color, "
        "coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "botanical leaves": (
        "A cute botanical leaf, flat 2D design, pure white background, "
        "thick bold BLACK outline only, single rounded leaf shape, "
        "central midrib, 5 curved side veins, slightly asymmetric, "
        "zero fill zero color, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "christmas snowflake": (
        "A cute kawaii snowflake, flat 2D design, pure white background, "
        "thick bold BLACK outline only, 6 identical arms with 2 branches each, "
        "perfectly symmetrical, zero fill zero color, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "halloween ghost": (
        "A cute kawaii ghost, flat 2D design, pure white background, "
        "thick bold BLACK outline only, round dome top, wavy bottom with 3 bumps, "
        "two large oval eyes, small O mouth, zero fill zero color, "
        "coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "halloween pumpkin": (
        "A cute kawaii pumpkin, flat 2D design, pure white background, "
        "thick bold BLACK outline only, round pumpkin body with 5 vertical segments, "
        "short stem, triangle eyes, jagged smile, zero fill zero color, "
        "coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "easter bunny": (
        "A cute kawaii bunny head, flat 2D design, pure white background, "
        "thick bold BLACK outline only, round face, two tall oval ears, "
        "dot eyes, small round nose, zero fill zero color, "
        "coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "easter egg": (
        "A cute kawaii easter egg, flat 2D design, pure white background, "
        "thick bold BLACK outline only, oval egg shape taller than wide, "
        "zigzag band across middle, small dots above and below band, "
        "zero fill zero color, coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
    "gingerbread house": (
        "A cute kawaii gingerbread house, flat 2D design, pure white background, "
        "thick bold BLACK outline only, square base with triangular roof, "
        "centered door, two windows, zero fill zero color, "
        "coloring book style, cookie cutter template, "
        "pure WHITE background only, single centered object, no other objects no pencils no props"
        ", NO 3D effect NO drop shadow NO shading NO depth"
    ),
}
_DALLE_DEFAULT = (
    "{topic} black silhouette cookie cutter shape on pure white background. "
    "Solid black filled shape only, no outlines, no gradients, no shading, "
    "no internal details. Flat graphic like a rubber stamp. High contrast."
)


def _make_svg_real(
    topic: str,
    product_type: str,
    size: str,
    out_path: Path,
) -> dict:
    """
    Generuje SVG przez Claude API z retry i walidacją ścieżki.
    Fallback do mock jeśli API niedostępne lub walidacja nie przejdzie.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set – falling back to mock SVG")
        return _make_svg_mock(topic, product_type, size, out_path)

    size_mm = SIZE_MM.get(size.upper(), 75.0)
    cx = size_mm / 2
    cy = size_mm / 2
    s  = size_mm * 0.44

    # Przykładowe ścieżki dla referencji
    heart_example = (
        f"M {cx:.1f},{cy - s * 0.05:.1f} "
        f"C {cx + s * 0.12:.1f},{cy - s * 0.58:.1f} {cx + s * 0.94:.1f},{cy - s * 0.58:.1f} {cx + s * 0.52:.1f},{cy - s * 0.30:.1f} "
        f"C {cx + s * 1.05:.1f},{cy + s * 0.05:.1f} {cx + s * 0.60:.1f},{cy + s * 0.37:.1f} {cx:.1f},{cy + s * 0.55:.1f} "
        f"C {cx - s * 0.60:.1f},{cy + s * 0.37:.1f} {cx - s * 1.05:.1f},{cy + s * 0.05:.1f} {cx - s * 0.52:.1f},{cy - s * 0.30:.1f} "
        f"C {cx - s * 0.94:.1f},{cy - s * 0.58:.1f} {cx - s * 0.12:.1f},{cy - s * 0.58:.1f} {cx:.1f},{cy - s * 0.05:.1f} Z"
    )
    star_pts = []
    for i in range(10):
        a = math.radians(i * 36 - 90)
        r = s * 0.50 if i % 2 == 0 else s * 0.21
        star_pts.append(f"{cx + r * math.cos(a):.1f},{cy + r * math.sin(a):.1f}")
    star_example = "M " + " L ".join(star_pts) + " Z"

    shape_hint = SHAPE_HINTS.get(topic.lower(), "")
    hint_line = f"\nShape guide: {shape_hint}" if shape_hint else ""

    prompt = f"""You are an SVG path engineer specializing in cute kawaii cookie cutter designs for 3D printing.

Task: Generate SVG path(s) depicting a **{topic}** in cute kawaii cartoon style.{hint_line}

Style requirements:
- cute kawaii cartoon style, chubby rounded proportions
- bold outlines suitable for 3D printing (no thin elements under 1.2mm)
- simple recognizable silhouette, no text

Specifications:
- ViewBox: 0 0 {size_mm} {size_mm} (coordinates in mm)
- Center: ({cx:.1f}, {cy:.1f})
- Shape fills roughly {s * 0.85:.1f}–{s * 1.0:.1f} mm radius from center
- Use SVG path commands: M, L, C, Q, Z (uppercase only, avoid A arcs)
- Each subpath: one M at start, end with Z
- Multiple subpaths allowed (separate with space between Z and M)
- Minimum 8 anchor points per subpath for smooth curves
- All coordinates within [3, {size_mm - 3:.0f}] on both axes

Reference — correct heart path:
{heart_example}

Output ONLY the path `d` value — no XML, no quotes, no markdown, no explanation.
"""

    client = anthropic.Anthropic(api_key=api_key)
    last_error = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        retry_note = ""
        if attempt > 1 and last_error:
            retry_note = f"\n\nPrevious attempt failed validation: {last_error}\nPlease fix this issue."

        try:
            msg = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system="You are an expert SVG path engineer. Output only raw SVG path d= values. Never include XML tags, markdown, or explanations.",
                messages=[{"role": "user", "content": prompt + retry_note}],
            )
            path_d = msg.content[0].text.strip()

            # Usuń ewentualne cudzysłowy lub d="..."
            path_d = re.sub(r'^d\s*=\s*["\']', "", path_d)
            path_d = path_d.strip("\"'")

            ok, reason = _validate_path(path_d, size_mm)
            if not ok:
                last_error = reason
                log.warning("Attempt %d/%d: path validation failed: %s", attempt, _MAX_RETRIES, reason)
                continue

            # S2.3: generuj stamp elements procedurally (no second API call)
            shape_key = _detect_shape(topic)
            stamp_elements = _stamp_elements_mock(shape_key, cx, cy, size_mm)

            log.info("Claude SVG path OK (attempt %d): %s", attempt, out_path)
            return _write_svg(path_d, out_path, size_mm, product_type, topic, size, "claude_generated", stamp_elements)

        except Exception as e:
            last_error = str(e)
            log.warning("Attempt %d/%d: Claude API error: %s", attempt, _MAX_RETRIES, e)

    log.warning("All %d attempts failed (%s) — falling back to mock", _MAX_RETRIES, last_error)
    return _make_svg_mock(topic, product_type, size, out_path)


# ── klasa agenta ─────────────────────────────────────────────────────────────

class DesignAgent:
    def __init__(self, mode: str = "mock"):
        self.mode = mode
        if mode == "dalle":
            self._make_svg = _make_svg_dalle_potrace
        elif mode in ("real", "auto"):
            self._make_svg = _make_svg_real
        else:
            self._make_svg = _make_svg_mock

    def generate(
        self,
        topic: str,
        product_type: str = "cutter",
        sizes: list[str] | None = None,
        output_dir: Path | None = None,
        slug: str | None = None,
    ) -> dict:
        """
        Generuje pliki SVG dla każdego rozmiaru.

        Args:
            topic:        Temat produktu, np. "floral wreath"
            product_type: "cutter" | "stamp" | "set"
            sizes:        Lista rozmiarów, np. ['S', 'M', 'L']
            output_dir:   Katalog nadrzędny (domyślnie data/products/)
            slug:         Slug produktu (opcjonalnie)

        Returns:
            {
              'success': bool,
              'slug': str,
              'topic': str,
              'product_type': str,
              'mode': str,
              'files': [{'size', 'path', 'width_mm', 'height_mm', 'shape'}],
              'errors': list  # tylko gdy były błędy
            }
        """
        if sizes is None:
            sizes = ["M"]
        if output_dir is None:
            output_dir = DATA_DIR

        slug = slug or _slugify(topic)
        # v3 struktura: {output_dir}/{product_type}/{slug}/source/
        source_dir = Path(output_dir) / product_type / slug / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        files  = []
        errors = []

        for size in sizes:
            size_up = size.upper()
            if size_up not in SIZE_MM:
                log.warning("Unknown size '%s' – skipping", size)
                errors.append(f"Unknown size: {size}")
                continue

            # Krótkie nazwy plików: S.svg, M.svg, L.svg
            out_path = source_dir / f"{size_up}.svg"

            try:
                file_info = self._make_svg(topic, product_type, size_up, out_path)
                files.append(file_info)
            except Exception as e:
                log.error("Failed to generate SVG for size %s: %s", size, e)
                errors.append(f"Size {size}: {e}")

        success = len(files) > 0

        result: dict = {
            "success": success,
            "slug": slug,
            "topic": topic,
            "product_type": product_type,
            "mode": self.mode,
            "files": files,
        }
        if errors:
            result["errors"] = errors

        # Zapis metadanych: {output_dir}/{product_type}/{slug}/design.json
        meta_path = Path(output_dir) / product_type / slug / "design.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        log.info("Saved design meta: %s", meta_path)

        return result


# ── factory ───────────────────────────────────────────────────────────────────

def create_design_agent(mode: str = "mock") -> DesignAgent:
    """
    Tworzy instancję DesignAgent.

    Args:
        mode: 'mock' - SVG z predefiniowanych kształtów (bez API, do testów)
              'real' - SVG przez Claude API z walidacją i retry (produkcja)
              'auto' - real jeśli ANTHROPIC_API_KEY dostępny, inaczej mock
    """
    if mode == "auto" and not os.getenv("ANTHROPIC_API_KEY"):
        log.info("auto mode: ANTHROPIC_API_KEY not set, using mock")
        return DesignAgent("mock")
    return DesignAgent(mode)


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
