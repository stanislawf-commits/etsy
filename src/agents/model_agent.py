"""
model_agent.py - konwertuje SVG -> STL dla produktow 3D (cuttery, stemple).

Tryby:
  openscad    - generuje .scad i wywoluje openscad CLI
  pure_python - bezposredni zapis binarnego STL (triangulacja wlasna)
  auto        - openscad jesli dostepny, inaczej pure_python

Walidacja STL:
  - Podstawowa (format binarny, rozmiar pliku) — zawsze
  - trimesh (watertight, objętość, normalne) — gdy trimesh zainstalowany

Interfejs:
  agent = create_model_agent('auto')
  result = agent.generate(svg_path, product_type, size_key, output_dir)

Uruchomienie standalone:
  python3 src/agents/model_agent.py
"""

import json
import logging
import math
import pathlib
import re
import struct
import subprocess
import tempfile
from pathlib import Path

from src.utils.config_loader import cfg

log = logging.getLogger(__name__)

BEZIER_SAMPLES = 32  # samples per Bézier curve segment (higher = smoother edges)


def _cutter_cfg() -> dict:
    """Zwraca parametry cutter z product_types.yaml."""
    return cfg("product_types").get("cutter", {})

def _stamp_cfg() -> dict:
    return cfg("product_types").get("stamp", {})

def _size_mm_map() -> dict:
    """Buduje mapę size_key → width_mm z product_types.yaml (cutter jako referencja)."""
    sizes_raw = _cutter_cfg().get("sizes", {})
    return {k: float(v.get("width_mm", 75.0)) for k, v in sizes_raw.items()}


# ── Stałe fallback (używane przez klasy przed inicjalizacją, cfg ważniejszy) ──

CUTTING_EDGE_MM: float  = 0.40
WALL_THICK_MM: float    = 1.80
BASE_THICK_MM: float    = 4.00
TOTAL_HEIGHT_MM: float  = 12.0
RELIEF_HEIGHT_MM: float = 1.50

SIZE_MM: dict = {
    "S":    60.0,
    "M":    75.0,
    "L":    90.0,
    "XL":  110.0,
    "XXL": 120.0,
    "XXXL":150.0,
}


# ── SVGPathParser ──────────────────────────────────────────────────────────────

class SVGPathParser:
    """Parsuje elementy SVG -> lista konturow jako punkty (x, y) w mm."""

    def parse(self, svg_content: str) -> list:
        scale = self._extract_scale(svg_content)
        contours = []

        for d_attr in re.findall(r'<path[^>]+\bd="([^"]+)"', svg_content, re.IGNORECASE):
            contours.extend(self._parse_d(d_attr, scale))

        for pts_attr in re.findall(r'<polygon[^>]+\bpoints="([^"]+)"', svg_content, re.IGNORECASE):
            pts = self._parse_points_attr(pts_attr, scale)
            if len(pts) >= 3:
                contours.append(pts)

        for pts_attr in re.findall(r'<polyline[^>]+\bpoints="([^"]+)"', svg_content, re.IGNORECASE):
            pts = self._parse_points_attr(pts_attr, scale)
            if len(pts) >= 2:
                contours.append(pts)

        for m in re.finditer(r'<circle([^>]+)>', svg_content, re.IGNORECASE):
            attrs = m.group(1)
            cx = self._attr_float(attrs, "cx", 0.0) * scale
            cy = self._attr_float(attrs, "cy", 0.0) * scale
            r  = self._attr_float(attrs, "r",  0.0) * scale
            if r > 0:
                contours.append(self._circle_points(cx, cy, r))

        for m in re.finditer(r'<ellipse([^>]+)>', svg_content, re.IGNORECASE):
            attrs = m.group(1)
            cx = self._attr_float(attrs, "cx", 0.0) * scale
            cy = self._attr_float(attrs, "cy", 0.0) * scale
            rx = self._attr_float(attrs, "rx", 0.0) * scale
            ry = self._attr_float(attrs, "ry", 0.0) * scale
            if rx > 0 and ry > 0:
                contours.append(self._ellipse_points(cx, cy, rx, ry))

        for m in re.finditer(r'<rect([^>]+)>', svg_content, re.IGNORECASE):
            attrs = m.group(1)
            tag = m.group(0)
            if 'fill="white"' in tag or "fill='white'" in tag:
                continue
            x = self._attr_float(attrs, "x",      0.0) * scale
            y = self._attr_float(attrs, "y",      0.0) * scale
            w = self._attr_float(attrs, "width",  0.0) * scale
            h = self._attr_float(attrs, "height", 0.0) * scale
            if w > 0 and h > 0:
                contours.append([(x, y), (x+w, y), (x+w, y+h), (x, y+h)])

        # Usuń zamykający duplikat: jeśli ostatni punkt == pierwszy, usuń go
        cleaned = []
        for c in contours:
            if len(c) >= 3 and c[-1] == c[0]:
                c = c[:-1]
            if len(c) >= 3:
                cleaned.append(c)
        return cleaned

    def _extract_scale(self, svg_content: str) -> float:
        m_vb = re.search(r'viewBox="([^"]+)"', svg_content, re.IGNORECASE)
        m_w  = re.search(r'\bwidth="([\d.]+)mm"', svg_content, re.IGNORECASE)
        if m_vb and m_w:
            parts = m_vb.group(1).split()
            if len(parts) == 4:
                vb_w = float(parts[2])
                w_mm = float(m_w.group(1))
                if vb_w > 0:
                    return w_mm / vb_w
        return 1.0

    def _attr_float(self, attrs: str, name: str, default: float) -> float:
        m = re.search(rf'\b{name}="([\d.+-]+)"', attrs)
        return float(m.group(1)) if m else default

    def _parse_points_attr(self, pts_str: str, scale: float) -> list:
        nums = [float(x) for x in re.split(r'[\s,]+', pts_str.strip()) if x]
        return [(nums[i]*scale, nums[i+1]*scale) for i in range(0, len(nums)-1, 2)]

    def _circle_points(self, cx: float, cy: float, r: float, n: int = 32) -> list:
        return [(cx + r*math.cos(2*math.pi*i/n), cy + r*math.sin(2*math.pi*i/n)) for i in range(n)]

    def _ellipse_points(self, cx: float, cy: float, rx: float, ry: float, n: int = 32) -> list:
        return [(cx + rx*math.cos(2*math.pi*i/n), cy + ry*math.sin(2*math.pi*i/n)) for i in range(n)]

    def _parse_d(self, d: str, scale: float) -> list:
        contours = []
        current = []
        x = y = x0 = y0 = 0.0
        tokens = re.findall(
            r'[MLHVCSQTAZmlhvcsqtaz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', d
        )
        i = 0
        cmd = 'M'

        def consume(n):
            nonlocal i
            vals = [float(tokens[i+k]) for k in range(n)]
            i += n
            return vals

        while i < len(tokens):
            t = tokens[i]
            if t.isalpha():
                cmd = t
                i += 1
                continue

            if cmd in ('M', 'm'):
                if current:
                    contours.append(current)
                    current = []
                dx, dy = consume(2)
                if cmd == 'm':
                    x += dx; y += dy
                else:
                    x, y = dx, dy
                x0, y0 = x, y
                current.append((x * scale, y * scale))
                cmd = 'l' if cmd == 'm' else 'L'

            elif cmd in ('L', 'l'):
                dx, dy = consume(2)
                if cmd == 'l':
                    x += dx; y += dy
                else:
                    x, y = dx, dy
                current.append((x * scale, y * scale))

            elif cmd in ('H', 'h'):
                v, = consume(1)
                x = x + v if cmd == 'h' else v
                current.append((x * scale, y * scale))

            elif cmd in ('V', 'v'):
                v, = consume(1)
                y = y + v if cmd == 'v' else v
                current.append((x * scale, y * scale))

            elif cmd in ('C', 'c'):
                vals = consume(6)
                if cmd == 'c':
                    x1, y1 = x+vals[0], y+vals[1]
                    x2, y2 = x+vals[2], y+vals[3]
                    ex, ey = x+vals[4], y+vals[5]
                else:
                    x1, y1 = vals[0], vals[1]
                    x2, y2 = vals[2], vals[3]
                    ex, ey = vals[4], vals[5]
                for k in range(1, BEZIER_SAMPLES + 1):
                    tk = k / BEZIER_SAMPLES
                    bx = (1-tk)**3*x + 3*(1-tk)**2*tk*x1 + 3*(1-tk)*tk**2*x2 + tk**3*ex
                    by = (1-tk)**3*y + 3*(1-tk)**2*tk*y1 + 3*(1-tk)*tk**2*y2 + tk**3*ey
                    current.append((bx * scale, by * scale))
                x, y = ex, ey

            elif cmd in ('Q', 'q'):
                vals = consume(4)
                if cmd == 'q':
                    cx_, cy_ = x+vals[0], y+vals[1]
                    ex, ey   = x+vals[2], y+vals[3]
                else:
                    cx_, cy_ = vals[0], vals[1]
                    ex, ey   = vals[2], vals[3]
                for k in range(1, BEZIER_SAMPLES + 1):
                    tk = k / BEZIER_SAMPLES
                    bx = (1-tk)**2*x + 2*(1-tk)*tk*cx_ + tk**2*ex
                    by = (1-tk)**2*y + 2*(1-tk)*tk*cy_ + tk**2*ey
                    current.append((bx * scale, by * scale))
                x, y = ex, ey

            elif cmd in ('A', 'a'):
                vals = consume(7)
                rx_a, ry_a, rot_a, large, sweep, ex, ey = vals
                if cmd == 'a':
                    ex += x; ey += y
                pts = self._arc_pts(x, y, rx_a, ry_a, rot_a,
                                    int(large), int(sweep), ex, ey)
                current.extend(pts)
                x, y = ex, ey

            elif cmd in ('Z', 'z'):
                if current and len(current) >= 3:
                    contours.append(current)
                current = []
                x, y = x0, y0

            else:
                i += 1

        if current and len(current) >= 3:
            contours.append(current)
        return contours

    def _arc_pts(self, x1: float, y1: float, rx: float, ry: float,
                 phi_deg: float, large_arc: int, sweep: int,
                 x2: float, y2: float, n: int = 24) -> list:
        """Prawdziwa konwersja luku SVG na punkty (SVG spec endpoint->center)."""
        if rx < 1e-9 or ry < 1e-9:
            return [(x2, y2)]
        phi = math.radians(phi_deg)
        cp, sp = math.cos(phi), math.sin(phi)
        dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
        x1p =  cp * dx + sp * dy
        y1p = -sp * dx + cp * dy
        x1p2, y1p2 = x1p * x1p, y1p * y1p
        rx2, ry2 = rx * rx, ry * ry
        lam = x1p2 / rx2 + y1p2 / ry2
        if lam > 1:
            sq = math.sqrt(lam)
            rx *= sq; ry *= sq
            rx2, ry2 = rx * rx, ry * ry
        num = max(0.0, rx2 * ry2 - rx2 * y1p2 - ry2 * x1p2)
        den = rx2 * y1p2 + ry2 * x1p2
        sq  = math.sqrt(num / den) if den > 1e-12 else 0.0
        if large_arc == sweep:
            sq = -sq
        cxp =  sq * rx * y1p / ry
        cyp = -sq * ry * x1p / rx
        cx = cp * cxp - sp * cyp + (x1 + x2) / 2
        cy = sp * cxp + cp * cyp + (y1 + y2) / 2

        def _angle(ux, uy, vx, vy):
            n_ = math.sqrt(ux*ux + uy*uy) * math.sqrt(vx*vx + vy*vy)
            if n_ < 1e-12:
                return 0.0
            c = max(-1.0, min(1.0, (ux*vx + uy*vy) / n_))
            a = math.acos(c)
            return -a if ux * vy - uy * vx < 0 else a

        ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
        vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
        theta1 = _angle(1.0, 0.0, ux, uy)
        dtheta = _angle(ux, uy, vx, vy)
        if sweep == 0 and dtheta > 0:
            dtheta -= 2 * math.pi
        elif sweep == 1 and dtheta < 0:
            dtheta += 2 * math.pi

        pts = []
        for i in range(1, n + 1):
            t = theta1 + dtheta * i / n
            px = cp * rx * math.cos(t) - sp * ry * math.sin(t) + cx
            py = sp * rx * math.cos(t) + cp * ry * math.sin(t) + cy
            pts.append((px, py))
        return pts


# ── OpenSCADGenerator ─────────────────────────────────────────────────────────

class OpenSCADGenerator:
    """Generuje kod .scad dla cutterow i stempli."""

    def generate_scad(self, contours: list, product_type: str, size_mm: float, slug: str) -> str:
        norm = self._normalize(contours, size_mm)
        if product_type == "stamp":
            return self._scad_stamp(norm, slug)
        elif product_type == "combo":
            return self._scad_cutter(norm, slug) + "\n" + self._scad_stamp(norm, slug)
        return self._scad_cutter(norm, slug)

    def _normalize(self, contours: list, size_mm: float) -> list:
        all_pts = [p for c in contours for p in c]
        if not all_pts:
            return contours
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span = max(max_x - min_x, max_y - min_y) or 1.0
        sc = size_mm * 0.90 / span
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        return [[ ((p[0]-cx)*sc, (p[1]-cy)*sc) for p in c ] for c in contours]

    def _single_polygon(self, contour: list) -> str:
        pts_str = ", ".join(f"[{p[0]:.4f},{p[1]:.4f}]" for p in contour)
        return f"polygon(points=[{pts_str}]);"

    def _union_extrude(self, contours: list, height: float, offset_r: float = 0.0,
                       z_offset: float = 0.0) -> str:
        """Generuje union() { linear_extrude... } dla kazdego konturu osobno."""
        lines = []
        if z_offset:
            lines.append(f"translate([0,0,{z_offset}])")
        lines.append("union() {")
        for c in contours:
            poly = self._single_polygon(c)
            if offset_r != 0.0:
                lines.append(f"  linear_extrude(height={height})"
                             f" {{ offset(r={offset_r}) {{ {poly} }} }}")
            else:
                lines.append(f"  linear_extrude(height={height}) {{ {poly} }}")
        lines.append("}")
        return "\n".join(lines)

    def _scad_cutter(self, contours: list, slug: str) -> str:
        body   = self._union_extrude(contours, TOTAL_HEIGHT_MM, offset_r=WALL_THICK_MM)
        hollow = self._union_extrude(contours, TOTAL_HEIGHT_MM, offset_r=-CUTTING_EDGE_MM,
                                     z_offset=BASE_THICK_MM)
        base   = self._union_extrude(contours, BASE_THICK_MM,   offset_r=WALL_THICK_MM)
        return (
            f"$fn=64;\n"
            f"// Cutter: {slug}\n"
            f"// wall={WALL_THICK_MM}mm edge={CUTTING_EDGE_MM}mm"
            f" base={BASE_THICK_MM}mm h={TOTAL_HEIGHT_MM}mm\n"
            f"difference() {{\n"
            f"  {body}\n"
            f"  {hollow}\n"
            f"}}\n"
            f"{base}\n"
        )

    def _scad_stamp(self, contours: list, slug: str) -> str:
        base   = self._union_extrude(contours, BASE_THICK_MM,    offset_r=WALL_THICK_MM)
        relief = self._union_extrude(contours, RELIEF_HEIGHT_MM, z_offset=BASE_THICK_MM)
        return (
            f"$fn=64;\n"
            f"// Stamp: {slug}\n"
            f"{base}\n"
            f"{relief}\n"
        )


# ── PurePythonSTLWriter ───────────────────────────────────────────────────────

class PurePythonSTLWriter:
    """Generuje binarne pliki STL bez zewnetrznych zaleznosci."""

    def generate_cutter_stl(self, contour: list, config: dict, output_path: Path) -> int:
        """Generuje watertight STL cuttera.

        Struktura (z=0 = ostrze/dół, z=wall_z = baza/uchwyt u góry):
          [A] Spód (z=0): annular ring ostrza (blade_in → outer)
          [B+C] Strefa taper (z=0..taper_h): outer stały, inner blade→full
          [D+E] Prosta strefa tnąca (z=taper_h..cookie_h): proste ściany
          [F+G] Zamknięcie góry strefy tnącej (z=cookie_h): ring + face
          [H]   Ścianki bazy (z=cookie_h..wall_z)
          [I]   Wierzch bazy (z=wall_z)
        """
        base_h   = config.get("base_thick",   BASE_THICK_MM)
        wall_z   = config.get("total_height", TOTAL_HEIGHT_MM)
        wall_w   = config.get("wall_thick",   WALL_THICK_MM)
        blade    = config.get("cutting_edge", CUTTING_EDGE_MM)
        taper_h  = config.get("taper_height", 3.0)

        # Kluczowe kontury (wszystkie offsety od outer, nie od contour)
        outer  = self._offset_contour(contour, wall_w)   # zewnętrzna krawędź (stała)
        b_in   = self._offset_contour(outer, -blade)     # inner przy ostrzu (z=0)
        f_in   = self._offset_contour(outer, -wall_w)    # inner przy pełnej ścianie ≈ contour

        cookie_h = wall_z - base_h  # wysokość strefy tnącej

        triangles = []

        # [A] Spód z=0: cienki pierścień ostrza (annular face)
        triangles.extend(self._ring(b_in, outer, 0.0, flip=True))

        # [B+C] Strefa taper (z=0..taper_h): outer stały, inner b_in→f_in
        triangles.extend(self._build_taper_section(outer, 0.0, taper_h, blade, wall_w))

        # [D+E] Prosta strefa tnąca (z=taper_h..cookie_h)
        if cookie_h > taper_h:
            straight = cookie_h - taper_h
            triangles.extend(self.extrude_contour(outer, straight, taper_h))
            triangles.extend(self.extrude_contour(f_in,  straight, taper_h, flip=True))

        # [G] Zamknięcie góry strefy tnącej (z=cookie_h): tylko cap f_in
        # Uwaga: nie ma _ring tutaj — outer boundary już domknięty przez D+H,
        # f_in boundary już domknięty przez E+G (3. trójkąt = non-manifold)
        triangles.extend(self._triangulate_flat(f_in, cookie_h, flip=False))

        # [H] Ścianki bazy (z=cookie_h..wall_z)
        triangles.extend(self.extrude_contour(outer, base_h, cookie_h))

        # [I] Wierzch bazy (z=wall_z)
        triangles.extend(self._triangulate_flat(outer, wall_z, flip=False))

        self.write_binary_stl(triangles, output_path)
        return len(triangles)

    def generate_stamp_stl(self, contour: list, config: dict, output_path: Path) -> int:
        base_h   = config.get("base_thick",    BASE_THICK_MM)
        relief_h = config.get("relief_height", RELIEF_HEIGHT_MM)
        wall_w   = config.get("wall_thick",    WALL_THICK_MM)

        outer = self._offset_contour(contour, wall_w)
        triangles = []
        triangles.extend(self._triangulate_flat(outer,  0.0,    flip=True))
        triangles.extend(self.extrude_contour(outer,  base_h, 0.0))
        triangles.extend(self._ring(contour, outer, base_h, flip=True))
        triangles.extend(self.extrude_contour(contour, relief_h, base_h))
        triangles.extend(self._triangulate_flat(contour, base_h + relief_h, flip=False))

        self.write_binary_stl(triangles, output_path)
        return len(triangles)

    def write_binary_stl(self, triangles: list, output_path: Path) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        header_str = b"Binary STL generated by etsy3d model_agent"
        header = header_str + b" " * (80 - len(header_str))
        n = len(triangles)
        buf = bytearray(header + struct.pack("<I", n))
        for tri in triangles:
            n_vec, v0, v1, v2 = tri
            buf += struct.pack("<fff", *n_vec)
            buf += struct.pack("<fff", *v0)
            buf += struct.pack("<fff", *v1)
            buf += struct.pack("<fff", *v2)
            buf += struct.pack("<H", 0)
        output_path.write_bytes(bytes(buf))

    def extrude_contour(self, contour: list, height: float, base_z: float = 0.0, flip: bool = False) -> list:
        triangles = []
        n = len(contour)
        for i in range(n):
            a = contour[i]
            b = contour[(i+1) % n]
            v0 = (a[0], a[1], base_z)
            v1 = (b[0], b[1], base_z)
            v2 = (b[0], b[1], base_z + height)
            v3 = (a[0], a[1], base_z + height)
            norm = self._face_normal(v0, v1, v2)
            if flip:
                fn = (-norm[0], -norm[1], -norm[2])
                triangles.append((fn, v0, v2, v1))
                triangles.append((fn, v0, v3, v2))
            else:
                triangles.append((norm, v0, v1, v2))
                triangles.append((norm, v0, v2, v3))
        return triangles

    def _earclip_triangulate(self, points: list) -> list:
        """Ear-clipping triangulation dla kształtów wklęsłych. O(n²), max ~200 pkt."""
        pts = list(points)
        n = len(pts)
        if n < 3:
            return []

        def cross2d(o, a, b):
            return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

        def point_in_triangle(p, a, b, c):
            d1 = cross2d(p, a, b)
            d2 = cross2d(p, b, c)
            d3 = cross2d(p, c, a)
            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
            return not (has_neg and has_pos)

        # upewnij się że orientacja CCW
        area = sum(cross2d(pts[0], pts[i], pts[i+1]) for i in range(1, n-1))
        if area < 0:
            pts = pts[::-1]

        indices = list(range(n))
        triangles = []

        while len(indices) > 3:
            ear_found = False
            for idx_pos, vi in enumerate(indices):
                prev_i = indices[(idx_pos - 1) % len(indices)]
                next_i = indices[(idx_pos + 1) % len(indices)]
                a, b, c = pts[prev_i], pts[vi], pts[next_i]

                if cross2d(a, b, c) <= 0:  # wklęsły — nie jest uchem
                    continue

                is_ear = True
                for other_pos, other_i in enumerate(indices):
                    if other_i in (prev_i, vi, next_i):
                        continue
                    if point_in_triangle(pts[other_i], a, b, c):
                        is_ear = False
                        break

                if is_ear:
                    triangles.append((prev_i, vi, next_i))
                    indices.pop(idx_pos)
                    ear_found = True
                    break

            if not ear_found:
                break  # zdegenerowany wielokąt

        if len(indices) == 3:
            triangles.append(tuple(indices))

        return triangles

    def _triangulate_flat(self, contour: list, z: float, flip: bool = False) -> list:
        """Triangulacja płaskiej powierzchni — używa ear-clipping (poprawne dla kształtów wklęsłych)."""
        if len(contour) < 3:
            return []
        norm = (0.0, 0.0, -1.0 if flip else 1.0)
        idx_triples = self._earclip_triangulate(contour)
        pts = list(contour)
        triangles = []
        for i0, i1, i2 in idx_triples:
            v0 = (pts[i0][0], pts[i0][1], z)
            v1 = (pts[i1][0], pts[i1][1], z)
            v2 = (pts[i2][0], pts[i2][1], z)
            if flip:
                triangles.append((norm, v0, v2, v1))
            else:
                triangles.append((norm, v0, v1, v2))
        return triangles

    def _lateral_ring(self, bottom_pts: list, top_pts: list, z_bottom: float, z_top: float) -> list:
        """Tworzy boczne ściany między dwoma konturami na różnych wysokościach."""
        triangles = []
        n = min(len(bottom_pts), len(top_pts))
        for i in range(n):
            a_bot = (bottom_pts[i][0],       bottom_pts[i][1],       z_bottom)
            b_bot = (bottom_pts[(i+1)%n][0], bottom_pts[(i+1)%n][1], z_bottom)
            a_top = (top_pts[i][0],          top_pts[i][1],          z_top)
            b_top = (top_pts[(i+1)%n][0],    top_pts[(i+1)%n][1],    z_top)
            norm0 = self._face_normal(a_bot, b_bot, b_top)
            norm1 = self._face_normal(a_bot, b_top, a_top)
            triangles.append((norm0, a_bot, b_bot, b_top))
            triangles.append((norm1, a_bot, b_top, a_top))
        return triangles

    def _offset_contour(self, points: list, distance: float) -> list:
        """Offset konturu o distance mm. Używa Shapely buffer(), ZAWSZE resampluję
        do tej samej liczby punktów co wejście — kluczowe dla watertight mesh.
        Fallback do skalowania centroidalnego gdy Shapely niedostępny."""
        if not points:
            return points
        if abs(distance) < 1e-9:
            return list(points)  # brak zmiany — te same wierzchołki
        try:
            from shapely.geometry import Polygon
            poly = Polygon(points)
            buffered = poly.buffer(distance, join_style="round", resolution=16)
            if buffered.is_empty:
                return list(points)
            n = len(points)
            ring = buffered.exterior
            total = ring.length
            if total < 1e-9:
                return list(points)
            # Resample do N punktów — offset 0.5 kroku unika duplikatu wrap-around
            # (Shapely ring start == end, i=0 i i=n wylądowałoby w tym samym punkcie)
            return [(ring.interpolate(total * (i + 0.5) / n).x,
                     ring.interpolate(total * (i + 0.5) / n).y) for i in range(n)]
        except ImportError:
            cx = sum(p[0] for p in points) / len(points)
            cy = sum(p[1] for p in points) / len(points)
            r_avg = sum(math.hypot(p[0]-cx, p[1]-cy) for p in points) / len(points)
            if r_avg < 1e-9:
                return list(points)
            sc = (r_avg + distance) / r_avg
            return [(cx + (p[0]-cx)*sc, cy + (p[1]-cy)*sc) for p in points]

    def _ring(self, inner: list, outer: list, z: float, flip: bool = False) -> list:
        triangles = []
        n = min(len(inner), len(outer))
        norm = (0.0, 0.0, -1.0 if flip else 1.0)
        for i in range(n):
            ai = (inner[i][0],       inner[i][1],       z)
            bi = (inner[(i+1)%n][0], inner[(i+1)%n][1], z)
            ao = (outer[i][0],       outer[i][1],       z)
            bo = (outer[(i+1)%n][0], outer[(i+1)%n][1], z)
            if flip:
                triangles.append((norm, ai, ao, bo))
                triangles.append((norm, ai, bo, bi))
            else:
                triangles.append((norm, ai, bi, bo))
                triangles.append((norm, ai, bo, ao))
        return triangles

    def _build_taper_section(self, outer_pts: list, z_bottom: float,
                              taper_h: float, wall_edge: float, wall_full: float) -> list:
        """Geometria taperowanego ostrza: strefa z_bottom..z_bottom+taper_h.
        Ściana przechodzi od wall_edge (ostrze) do wall_full (pełna grubość)."""
        steps = max(6, int(taper_h / 0.5))
        triangles = []

        prev_outer = self._offset_contour(outer_pts, 0)
        prev_inner = self._offset_contour(outer_pts, -wall_edge)
        prev_z = z_bottom

        for step in range(1, steps + 1):
            t = step / steps
            z = z_bottom + taper_h * t
            wall = wall_edge + (wall_full - wall_edge) * t

            curr_outer = self._offset_contour(outer_pts, 0)
            curr_inner = self._offset_contour(outer_pts, -wall)

            triangles.extend(self._lateral_ring(prev_outer, curr_outer, prev_z, z))
            triangles.extend(self._lateral_ring(curr_inner, prev_inner, z, prev_z))

            prev_outer, prev_inner, prev_z = curr_outer, curr_inner, z

        return triangles

    def _build_fillet(self, outer_pts: list, z_top: float, fillet_r: float, wall_full: float) -> list:
        """Zaokrąglenie górnej krawędzi — łuk od pionowej ściany do poziomego plateau."""
        fillet_steps = 4
        triangles = []
        prev_pts = self._offset_contour(outer_pts, 0)
        prev_z = z_top - fillet_r

        for step in range(1, fillet_steps + 1):
            angle = (math.pi / 2) * step / fillet_steps
            r_offset = fillet_r * (1 - math.cos(angle))
            z = z_top - fillet_r + fillet_r * math.sin(angle)
            curr_pts = self._offset_contour(outer_pts, r_offset)
            triangles.extend(self._lateral_ring(prev_pts, curr_pts, prev_z, z))
            prev_pts, prev_z = curr_pts, z

        return triangles

    def _face_normal(self, v0, v1, v2):
        ax, ay, az = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
        bx, by, bz = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
        nx = ay*bz - az*by
        ny = az*bx - ax*bz
        nz = ax*by - ay*bx
        length = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
        return (nx/length, ny/length, nz/length)


# ── STLValidator ──────────────────────────────────────────────────────────────

class STLValidator:
    """Waliduje pliki STL.

    Dwa poziomy walidacji:
    1. Podstawowa — format binarny/ASCII, rozmiar pliku, min trójkątów (zawsze)
    2. trimesh    — watertight, objętość > 0, normalne (gdy trimesh dostępny)
    """

    def validate(self, stl_path: Path, config: dict) -> dict:
        stl_path = Path(stl_path)
        if not stl_path.exists():
            return {"valid": False, "error": "File does not exist", "n_triangles": 0}

        size = stl_path.stat().st_size
        if size <= 84:
            return {"valid": False, "error": f"File too small ({size} B)", "n_triangles": 0}

        data = stl_path.read_bytes()

        # ── Format ASCII ──
        if data[:5].lower() == b"solid":
            n_tri = data.decode("ascii", errors="replace").count("facet normal")
            if n_tri < 10:
                return {"valid": False, "error": f"ASCII STL: too few triangles ({n_tri})",
                        "n_triangles": n_tri}
            result = {"valid": True, "n_triangles": n_tri, "file_size": size,
                      "stl_format": "ascii", "error": None}
            return self._trimesh_check(stl_path, result)

        # ── Format binarny ──
        try:
            n_tri = struct.unpack("<I", data[80:84])[0]
        except Exception as e:
            return {"valid": False, "error": f"Cannot read header: {e}", "n_triangles": 0}

        if n_tri < 10:
            return {"valid": False, "error": f"Too few triangles ({n_tri})", "n_triangles": n_tri}

        expected = 84 + n_tri * 50
        size_ok  = abs(size - expected) < 1024
        result   = {
            "valid":         size_ok,
            "n_triangles":   n_tri,
            "file_size":     size,
            "expected_size": expected,
            "stl_format":    "binary",
            "error":         None if size_ok else f"Size mismatch: {size} vs {expected}",
        }
        if not size_ok:
            return result
        return self._trimesh_check(stl_path, result)

    def _trimesh_check(self, stl_path: Path, base_result: dict) -> dict:
        """Rozszerza walidację o trimesh jeśli dostępny. Nie nadpisuje valid=True na False
        tylko na podstawie watertight — niektóre modele mają drobne luki i nadal drukują się OK.
        Dodaje pola: watertight, volume_mm3, trimesh_warnings."""
        try:
            import trimesh
        except ImportError:
            log.debug("trimesh not available — skipping mesh quality check")
            return base_result

        try:
            mesh = trimesh.load(str(stl_path), force="mesh")

            watertight = bool(mesh.is_watertight)
            volume     = float(mesh.volume) if watertight else 0.0
            warnings   = []

            if not watertight:
                warnings.append("mesh is not watertight (may have open edges)")
            if volume < 0:
                warnings.append(f"negative volume ({volume:.2f} mm³) — normals may be inverted")
            if mesh.is_empty:
                warnings.append("mesh is empty")

            base_result["watertight"]      = watertight
            base_result["volume_mm3"]      = round(volume, 2)
            base_result["trimesh_warnings"] = warnings

            if warnings:
                log.warning("STL quality issues in %s: %s", stl_path.name, "; ".join(warnings))
            else:
                log.debug("STL trimesh OK: %s (watertight, vol=%.1f mm³)", stl_path.name, volume)

        except Exception as exc:
            log.warning("trimesh check failed for %s: %s", stl_path.name, exc)
            base_result["trimesh_warnings"] = [f"trimesh check error: {exc}"]

        return base_result


# ── ModelAgent ────────────────────────────────────────────────────────────────

class ModelAgent:
    """Glowny agent: SVG -> STL."""

    def __init__(self, config: dict = None):
        self.config     = config or {}
        self.mode       = self._detect_mode()
        self.parser     = SVGPathParser()
        self.scad_gen   = OpenSCADGenerator()
        self.stl_writer = PurePythonSTLWriter()
        self.validator  = STLValidator()
        log.info("ModelAgent mode: %s", self.mode)

    def _detect_mode(self) -> str:
        forced = self.config.get("mode", "auto")
        if forced != "auto":
            return forced
        try:
            r = subprocess.run(["openscad", "--version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return "openscad"
        except Exception:
            pass
        return "pure_python"

    def generate(self, svg_path: Path, product_type: str, size_key: str, output_dir: Path) -> dict:
        svg_path   = Path(svg_path)
        output_dir = Path(output_dir)
        size_key   = size_key.upper()
        # Wymiary z config (fallback do stałych)
        size_map   = _size_mm_map()
        size_mm    = size_map.get(size_key, SIZE_MM.get(size_key, 75.0))
        slug       = svg_path.stem

        if not svg_path.exists():
            return {"stl_path": None, "valid": False, "n_triangles": 0,
                    "error": f"SVG not found: {svg_path}"}

        svg_content = svg_path.read_text(encoding="utf-8", errors="replace")
        contours = self.parser.parse(svg_content)

        if not contours:
            return {"stl_path": None, "valid": False, "n_triangles": 0,
                    "error": "No contours parsed from SVG"}

        main_contour = max(contours, key=len)
        stl_name = f"{slug}_{size_key}_{product_type}.stl"
        stl_path = output_dir / stl_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # Pobierz parametry z product_types.yaml lub użyj stałych jako fallback
        pt_cfg = _cutter_cfg() if product_type != "stamp" else _stamp_cfg()
        model_cfg = {
            "total_height":  float(pt_cfg.get("total_height",   TOTAL_HEIGHT_MM)),
            "base_thick":    float(pt_cfg.get("base_height",    BASE_THICK_MM)),
            "wall_thick":    float(pt_cfg.get("wall_thickness", WALL_THICK_MM)),
            "cutting_edge":  float(pt_cfg.get("blade_thickness", CUTTING_EDGE_MM)),
            "relief_height": float(pt_cfg.get("relief_height",  RELIEF_HEIGHT_MM)),
            "taper_height":  float(pt_cfg.get("taper_height",   3.0)),
            "fillet_top":    float(pt_cfg.get("fillet_top",     1.0)),
        }

        if self.mode == "openscad":
            n_tri = self._generate_via_openscad(contours, product_type, size_mm, slug, stl_path)
        elif product_type == "stamp":
            n_tri = self.stl_writer.generate_stamp_stl(main_contour, model_cfg, stl_path)
        else:
            n_tri = self.stl_writer.generate_cutter_stl(main_contour, model_cfg, stl_path)

        result = self.validator.validate(stl_path, model_cfg)
        result["stl_path"]    = str(stl_path)
        result["n_triangles"] = n_tri
        result["size_mm"]     = size_mm
        return result

    def generate_all(self, slug: str, product_type: str, source_dir: Path, output_dir: Path) -> dict:
        source_dir = Path(source_dir)
        output_dir = Path(output_dir)
        sizes_result = {}
        size_map = _size_mm_map()

        for size_key in size_map:
            size_lower = size_key.lower()
            candidates = [
                source_dir / f"{slug}-{size_key}.svg",
                source_dir / f"design_{size_lower}.svg",
                source_dir / f"{slug}_{size_key}.svg",
                source_dir / f"{slug}-{size_lower}.svg",
            ]
            svg_path = next((p for p in candidates if p.exists()), None)
            if svg_path is None:
                continue
            log.info("Processing %s -> %s", svg_path.name, size_key)
            sizes_result[size_key] = self.generate(svg_path, product_type, size_key, output_dir)

        return {"slug": slug, "product_type": product_type, "sizes": sizes_result}

    def _generate_via_openscad(self, contours, product_type, size_mm, slug, stl_path) -> int:
        scad_code = self.scad_gen.generate_scad(contours, product_type, size_mm, slug)
        with tempfile.NamedTemporaryFile(suffix=".scad", mode="w", delete=False) as f:
            f.write(scad_code)
            scad_path = f.name
        try:
            subprocess.run(
                ["openscad", "--export-format", "binstl",
                 "-o", str(stl_path), scad_path],
                capture_output=True, timeout=120, check=True,
            )
        finally:
            pathlib.Path(scad_path).unlink(missing_ok=True)
        if stl_path.exists() and stl_path.stat().st_size > 84:
            data = stl_path.read_bytes()
            if data[:5].lower() == b"solid":
                return data.decode("ascii", errors="replace").count("facet normal")
            return struct.unpack("<I", data[80:84])[0]
        return 0


# ── factory ───────────────────────────────────────────────────────────────────

def create_model_agent(mode: str = "auto") -> ModelAgent:
    """
    Tworzy instancje ModelAgent.

    Args:
        mode: 'auto'        - openscad jesli dostepny, inaczej pure_python
              'openscad'    - wymusza openscad CLI
              'pure_python' - wymusza wlasna triangulacje
    """
    return ModelAgent(config={"mode": mode})


# ── standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    DATA_DIR   = Path(__file__).parents[2] / "data" / "products"
    slug       = "floral-wreath-cutter"
    source_dir = DATA_DIR / slug / "source"
    output_dir = DATA_DIR / slug / "stl"

    print(f"\nModelAgent standalone test")
    print(f"  slug:       {slug}")
    print(f"  source_dir: {source_dir}")
    print(f"  output_dir: {output_dir}")

    agent  = create_model_agent("pure_python")
    result = agent.generate_all(
        slug=slug,
        product_type="cutter",
        source_dir=source_dir,
        output_dir=output_dir,
    )

    sizes = result.get("sizes", {})
    if not sizes:
        print("\nERROR: Brak wynikow — sprawdz czy SVG istnieja w source_dir")
    else:
        print(f"\nWyniki ({len(sizes)} rozmiarow):")
        for size_key, r in sizes.items():
            status = "OK" if r.get("valid") else "FAIL"
            n_tri  = r.get("n_triangles", 0)
            path   = r.get("stl_path", "-")
            err    = r.get("error") or ""
            print(f"  [{size_key}] {status:4s}  triangles={n_tri:6d}  {path}  {err}")
