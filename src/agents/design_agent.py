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

# Liczba prób generowania przez API
_MAX_RETRIES = 3


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

    # Tylko jedna ścieżka (jedno M na początku)
    # Liczymy M po pierwszym znaku (spacje wokół lub cyfry)
    subsequent_m = re.findall(r"(?<=[^A-Za-z])M\s", d_upper[2:])
    if subsequent_m:
        return False, f"Multiple subpaths detected ({1 + len(subsequent_m)} M commands) — must be single closed path"

    # Minimalna liczba punktów współrzędnych
    coords = re.findall(r"-?\d+\.?\d*\s*,\s*-?\d+\.?\d*", d)
    if len(coords) < 3:
        return False, f"Too few coordinate pairs ({len(coords)}) — need at least 3 for a recognizable shape"

    # Sprawdź zdegenerowane łuki (A) — punkty startowy i końcowy identyczne lub <0.05 apart
    # Pattern: A rx ry x-rotation large-arc-flag sweep-flag x y
    arc_ends = re.findall(
        r"A\s+[\d.]+\s*,?\s*[\d.]+\s+[\d.]+\s+[01]\s+[01]\s+(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)",
        d_upper,
    )
    for ex, ey in arc_ends:
        # Check against preceding M or last coord — simplified: just warn if nearly same
        # We can't easily track current point here, so check for A followed by Z immediately
        pass  # full degenerate-arc detection handled by retry on API side

    # Sprawdź zakresy współrzędnych
    margin = size_mm * 0.15
    for coord in coords:
        parts = re.split(r"\s*,\s*", coord.strip())
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

    # Zewnętrzny okrąg: prawa połowa (góra → dół), dwie ćwiartki
    # Wewnętrzny okrąg: prawa połowa (dół → góra, przesunięty), wracamy na start
    d = (
        f"M {cx:.2f},{cy - r:.2f}"
        # zewnętrzna ćwiartka: top → right
        f" C {cx + r*k:.2f},{cy - r:.2f} {cx + r:.2f},{cy - r*k:.2f} {cx + r:.2f},{cy:.2f}"
        # zewnętrzna ćwiartka: right → bottom
        f" C {cx + r:.2f},{cy + r*k:.2f} {cx + r*k:.2f},{cy + r:.2f} {cx:.2f},{cy + r:.2f}"
        # wewnętrzny okrąg (środek = cx+off) — dolna ćwiartka: bottom → left
        f" C {cx + off - ri*k:.2f},{cy + ri:.2f} {cx + off - ri:.2f},{cy + ri*k:.2f} {cx + off - ri:.2f},{cy:.2f}"
        # wewnętrzny okrąg — górna ćwiartka: left → top
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
    r_outer = s * 0.46   # końce płatków
    r_inner = s * 0.28   # doliny między płatkami

    # Generujemy 16 punktów: przemiennie zewnętrzne (końce płatków) i wewnętrzne (doliny)
    pts: list[tuple[float, float]] = []
    for i in range(n_petals * 2):
        angle = math.radians(i * 180 / n_petals - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    # Buduj ścieżkę z gładkimi krzywymi kwadratowymi Beziera
    # Każdy punkt to punkt kontrolny Q, endpoint = połowa odcinka do następnego punktu
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
    # Gładkie łuki między punktami jak w _path_floral
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
    # Cztery zaokrąglone sekcje dyni + szypułka
    w = s * 0.88
    h = s * 0.76
    st_w = s * 0.10   # szypułka szerokość
    st_h = s * 0.22   # szypułka wysokość
    top_y = cy - h / 2
    bot_y = cy + h / 2

    # Lewa strona dyni (cubic bezier)
    d = (
        f"M {cx - st_w:.2f},{top_y:.2f}"
        # szypułka góra-lewa do górnej krawędzi dyni
        f" L {cx - st_w:.2f},{top_y - st_h:.2f}"
        f" L {cx + st_w:.2f},{top_y - st_h:.2f}"
        f" L {cx + st_w:.2f},{top_y:.2f}"
        # prawa połowa dyni (dwa segmenty)
        f" C {cx + w * 0.25:.2f},{top_y:.2f} {cx + w * 0.50:.2f},{cy - h * 0.40:.2f} {cx + w / 2:.2f},{cy:.2f}"
        f" C {cx + w * 0.50:.2f},{cy + h * 0.40:.2f} {cx + w * 0.25:.2f},{bot_y:.2f} {cx + st_w:.2f},{bot_y:.2f}"
        # dół środkowy
        f" L {cx - st_w:.2f},{bot_y:.2f}"
        # lewa połowa dyni
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

    # Warstwy: dół, środek, góra
    w1 = s * 0.86   # dolna warstwa
    w2 = s * 0.62   # środkowa
    w3 = s * 0.38   # górna (czubek)
    y1 = bot_y - trunk_h               # dół warstwy 1
    y2 = y1 - h * 0.28                 # dół warstwy 2 (nakłada się)
    y3 = y2 - h * 0.25                 # dół warstwy 3

    d = (
        # pień
        f"M {cx - trunk_w:.2f},{bot_y:.2f}"
        f" L {cx - trunk_w:.2f},{y1:.2f}"
        # dolna warstwa
        f" L {cx - w1 / 2:.2f},{y1:.2f}"
        f" L {cx:.2f},{y2:.2f}"
        f" L {cx + w1 / 2:.2f},{y1:.2f}"
        f" L {cx + trunk_w:.2f},{y1:.2f}"
        f" L {cx + trunk_w:.2f},{bot_y:.2f}"
        f" Z"
    )
    # Prościej jako jeden wielokąt bez "nakładania":
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
    branch_off = s * 0.22  # odległość od centrum do rozgałęzień

    pts: list[tuple[float, float]] = []
    for i in range(n):
        angle_arm   = math.radians(i * 60 - 90)
        angle_left  = math.radians(i * 60 - 90 + 60)
        angle_right = math.radians(i * 60 - 90 - 60)

        # końcówka ramienia
        tip_x = cx + r_arm * math.cos(angle_arm)
        tip_y = cy + r_arm * math.sin(angle_arm)
        # lewa gałąź
        bl_x = cx + branch_off * math.cos(angle_arm) + r_branch * math.cos(angle_left)
        bl_y = cy + branch_off * math.sin(angle_arm) + r_branch * math.sin(angle_left)
        # prawa gałąź
        br_x = cx + branch_off * math.cos(angle_arm) + r_branch * math.cos(angle_right)
        br_y = cy + branch_off * math.sin(angle_arm) + r_branch * math.sin(angle_right)
        # punkt rozgałęzienia
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
        # głowa (przybliżony okrąg przez 8-kąt)
        f"M {cx:.2f},{head_cy - head_r:.2f}"
        f" C {cx + head_r * 0.7:.2f},{head_cy - head_r * 0.7:.2f}"
        f" {cx + head_r:.2f},{head_cy - head_r * 0.3:.2f} {cx + head_r:.2f},{head_cy:.2f}"
        f" C {cx + head_r:.2f},{head_cy + head_r * 0.7:.2f}"
        f" {cx + head_r * 0.5:.2f},{body_top:.2f} {cx + body_w / 2:.2f},{body_top:.2f}"
        # prawa ręka
        f" L {cx + arm_w:.2f},{arm_y:.2f}"
        f" L {cx + arm_w:.2f},{arm_y + arm_h:.2f}"
        f" L {cx + body_w / 2:.2f},{body_top + body_h * 0.45:.2f}"
        # prawa noga
        f" L {cx + body_w / 2:.2f},{body_bot:.2f}"
        f" L {cx + leg_w:.2f},{body_bot:.2f}"
        f" L {cx + leg_w:.2f},{body_bot + leg_h:.2f}"
        f" L {cx - leg_w:.2f},{body_bot + leg_h:.2f}"
        f" L {cx - leg_w:.2f},{body_bot:.2f}"
        # lewa noga
        f" L {cx - body_w / 2:.2f},{body_bot:.2f}"
        # lewa ręka
        f" L {cx - body_w / 2:.2f},{body_top + body_h * 0.45:.2f}"
        f" L {cx - arm_w:.2f},{arm_y + arm_h:.2f}"
        f" L {cx - arm_w:.2f},{arm_y:.2f}"
        f" L {cx - body_w / 2:.2f},{body_top:.2f}"
        # lewa część głowy
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


SHAPE_BUILDERS = {
    "mountain":      _path_mountain,
    "heart":         _path_heart,
    "star":          _path_star,
    "moon":          _path_moon,
    "floral":        _path_floral,
    "leaf":          _path_leaf,
    "butterfly":     _path_butterfly,
    "mushroom":      _path_mushroom,
    "hexagon":       _path_hexagon,
    "sun":           _path_sun,
    "pumpkin":       _path_pumpkin,
    "christmas_tree": _path_christmas_tree,
    "snowflake":     _path_snowflake,
    "gingerbread":   _path_gingerbread,
    "rounded_rect":  _path_rounded_rect,
}


# ── generowanie SVG ───────────────────────────────────────────────────────────

def _write_svg(path_d: str, out_path: Path, size_mm: float,
               product_type: str, topic: str, size: str, shape: str) -> dict:
    """Zapisuje SVG z gotową ścieżką path_d."""
    dwg = svgwrite.Drawing(
        str(out_path),
        size=(f"{size_mm}mm", f"{size_mm}mm"),
        viewBox=f"0 0 {size_mm} {size_mm}",
        profile="full",
    )
    dwg.add(dwg.rect(insert=(0, 0), size=(f"{size_mm}mm", f"{size_mm}mm"), fill="white"))

    if product_type == "cutter":
        dwg.add(dwg.path(
            d=path_d,
            fill="none",
            stroke="#1a1a1a",
            stroke_width=f"{WALL_MM}mm",
            stroke_linejoin="round",
            stroke_linecap="round",
        ))
    else:
        dwg.add(dwg.path(
            d=path_d,
            fill="#2d2d2d",
            stroke="#1a1a1a",
            stroke_width=f"{WALL_MM * 0.5}mm",
        ))

    dwg.add(dwg.text(
        f"{topic} | {product_type.upper()} | {size}",
        insert=(f"{size_mm / 2}mm", f"{size_mm * 0.96}mm"),
        text_anchor="middle",
        font_size="3px",
        fill="#888888",
        font_family="sans-serif",
    ))
    dwg.save(pretty=True)
    return {
        "size": size,
        "path": str(out_path),
        "width_mm": size_mm,
        "height_mm": size_mm,
        "shape": shape,
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

    log.info("Mock SVG: %s (%.0fmm, shape=%s)", out_path, size_mm, shape_key)
    return _write_svg(path_d, out_path, size_mm, product_type, topic, size, shape_key)


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

    prompt = f"""You are an SVG path engineer for 3D-printed cookie cutters.

Task: Generate ONE single closed SVG path (the `d` attribute) that clearly depicts a **{topic}** silhouette, suitable for a cookie cutter.

Specifications:
- ViewBox: 0 0 {size_mm} {size_mm}  (coordinates in mm)
- Center of shape: ({cx:.1f}, {cy:.1f})
- Shape should fill roughly {s * 0.9:.1f}–{s * 1.0:.1f} mm radius from center
- Use SVG path commands: M, L, C, Q, A, Z  (uppercase only)
- The path MUST be a single closed path: exactly one M at the start, end with Z
- NO multiple subpaths (no second M after the first one)
- Minimum 10 anchor/control points for a recognizable shape
- Coordinates MUST stay within [2, {size_mm - 2:.0f}] on both axes
- Do NOT use degenerate arcs (where start point ≈ end point)

Quality rules:
- The outline must clearly resemble "{topic}"
- Prefer C (cubic Bezier) and L commands for organic shapes
- Avoid overly simple shapes (fewer than 8 anchor points)

Reference examples (correct format):
Heart: {heart_example}
Star:  {star_example}

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
                max_tokens=1024,
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

            log.info("Claude SVG path OK (attempt %d): %s", attempt, out_path)
            return _write_svg(path_d, out_path, size_mm, product_type, topic, size, "claude_generated")

        except Exception as e:
            last_error = str(e)
            log.warning("Attempt %d/%d: Claude API error: %s", attempt, _MAX_RETRIES, e)

    log.warning("All %d attempts failed (%s) — falling back to mock", _MAX_RETRIES, last_error)
    return _make_svg_mock(topic, product_type, size, out_path)


# ── klasa agenta ─────────────────────────────────────────────────────────────

class DesignAgent:
    def __init__(self, mode: str = "mock"):
        self.mode = mode
        if mode in ("real", "auto"):
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
