"""
model_agent.py - konwertuje SVG -> STL dla produktow 3D (cuttery, stemple).

Tryby:
  openscad    - generuje .scad i wywoluje openscad CLI
  pure_python - bezposredni zapis binarnego STL (triangulacja wlasna)
  auto        - openscad jesli dostepny, inaczej pure_python

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

log = logging.getLogger(__name__)

# ── stalep food-safe (niezmienne) ─────────────────────────────────────────────

CUTTING_EDGE_MM: float  = 0.40
WALL_THICK_MM: float    = 1.80
BASE_THICK_MM: float    = 4.00
TOTAL_HEIGHT_MM: float  = 12.0
MIN_FILLET_MM: float    = 0.50
DRAFT_ANGLE_DEG: float  = 3.0
RELIEF_HEIGHT_MM: float = 1.50

SIZE_MM: dict = {
    "S":    60.0,
    "M":    75.0,
    "L":    90.0,
    "XL":  100.0,
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

        return [c for c in contours if len(c) >= 3]

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
                for k in range(1, 9):
                    tk = k / 8.0
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
                for k in range(1, 9):
                    tk = k / 8.0
                    bx = (1-tk)**2*x + 2*(1-tk)*tk*cx_ + tk**2*ex
                    by = (1-tk)**2*y + 2*(1-tk)*tk*cy_ + tk**2*ey
                    current.append((bx * scale, by * scale))
                x, y = ex, ey

            elif cmd in ('A', 'a'):
                vals = consume(7)
                _rx, _ry, _rot, large, sweep, ex, ey = vals
                if cmd == 'a':
                    ex += x; ey += y
                pts = self._arc_pts(x, y, ex, ey)
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

    def _arc_pts(self, x1, y1, x2, y2, n=12) -> list:
        return [(x1 + (x2-x1)*k/n, y1 + (y2-y1)*k/n) for k in range(1, n+1)]


# ── OpenSCADGenerator ─────────────────────────────────────────────────────────

class OpenSCADGenerator:
    """Generuje kod .scad dla cutterow i stempli."""

    def generate_scad(self, contours: list, product_type: str, size_mm: float, slug: str) -> str:
        norm = self._normalize(contours, size_mm)
        poly_code = self._contours_to_polygon(norm)
        if product_type == "stamp":
            return self._scad_stamp(poly_code, slug)
        elif product_type == "combo":
            return self._scad_cutter(poly_code, slug) + "\n" + self._scad_stamp(poly_code, slug)
        return self._scad_cutter(poly_code, slug)

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

    def _contours_to_polygon(self, contours: list) -> str:
        all_pts = []
        paths = []
        for c in contours:
            start = len(all_pts)
            all_pts.extend(c)
            paths.append(list(range(start, start + len(c))))
        pts_str  = ", ".join(f"[{p[0]:.4f},{p[1]:.4f}]" for p in all_pts)
        path_str = ", ".join(str(p) for p in paths)
        return f"polygon(points=[{pts_str}], paths=[{path_str}]);"

    def _scad_cutter(self, poly_code: str, slug: str) -> str:
        return (
            f"// Cutter: {slug}\n"
            f"// wall={WALL_THICK_MM}mm edge={CUTTING_EDGE_MM}mm base={BASE_THICK_MM}mm h={TOTAL_HEIGHT_MM}mm\n"
            f"difference() {{\n"
            f"  linear_extrude(height={TOTAL_HEIGHT_MM}) {{\n"
            f"    offset(r={WALL_THICK_MM}) {{ {poly_code} }}\n"
            f"  }}\n"
            f"  translate([0,0,{BASE_THICK_MM}]) {{\n"
            f"    linear_extrude(height={TOTAL_HEIGHT_MM}) {{\n"
            f"      offset(r={-CUTTING_EDGE_MM}) {{ {poly_code} }}\n"
            f"    }}\n"
            f"  }}\n"
            f"}}\n"
            f"linear_extrude(height={BASE_THICK_MM}) {{\n"
            f"  offset(r={WALL_THICK_MM}) {{ {poly_code} }}\n"
            f"}}\n"
        )

    def _scad_stamp(self, poly_code: str, slug: str) -> str:
        return (
            f"// Stamp: {slug}\n"
            f"linear_extrude(height={BASE_THICK_MM}) {{\n"
            f"  offset(r={WALL_THICK_MM}) {{ {poly_code} }}\n"
            f"}}\n"
            f"translate([0,0,{BASE_THICK_MM}]) {{\n"
            f"  linear_extrude(height={RELIEF_HEIGHT_MM}) {{ {poly_code} }}\n"
            f"}}\n"
        )


# ── PurePythonSTLWriter ───────────────────────────────────────────────────────

class PurePythonSTLWriter:
    """Generuje binarne pliki STL bez zewnetrznych zaleznosci."""

    def generate_cutter_stl(self, contour: list, config: dict, output_path: Path) -> int:
        base_h = config.get("base_thick",   BASE_THICK_MM)
        wall_z = config.get("total_height", TOTAL_HEIGHT_MM)
        wall_w = config.get("wall_thick",   WALL_THICK_MM)

        outer = self._offset_contour(contour, wall_w)
        triangles = []
        triangles.extend(self._triangulate_flat(outer,   0.0,    flip=True))
        triangles.extend(self._triangulate_flat(outer,   base_h, flip=False))
        triangles.extend(self.extrude_contour(outer,  base_h, 0.0))
        triangles.extend(self._ring(contour, outer, base_h, flip=False))
        triangles.extend(self.extrude_contour(contour, wall_z - base_h, base_h, flip=True))
        triangles.extend(self._triangulate_flat(contour, wall_z, flip=True))

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

    def _triangulate_flat(self, contour: list, z: float, flip: bool = False) -> list:
        if len(contour) < 3:
            return []
        triangles = []
        v0 = (contour[0][0], contour[0][1], z)
        norm = (0.0, 0.0, -1.0 if flip else 1.0)
        for i in range(1, len(contour) - 1):
            v1 = (contour[i][0],   contour[i][1],   z)
            v2 = (contour[i+1][0], contour[i+1][1], z)
            if flip:
                triangles.append((norm, v0, v2, v1))
            else:
                triangles.append((norm, v0, v1, v2))
        return triangles

    def _offset_contour(self, contour: list, offset: float) -> list:
        if not contour:
            return contour
        cx = sum(p[0] for p in contour) / len(contour)
        cy = sum(p[1] for p in contour) / len(contour)
        r_avg = sum(math.hypot(p[0]-cx, p[1]-cy) for p in contour) / len(contour)
        if r_avg < 1e-6:
            return contour
        sc = (r_avg + offset) / r_avg
        return [(cx + (p[0]-cx)*sc, cy + (p[1]-cy)*sc) for p in contour]

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
    """Waliduje pliki STL (format binarny)."""

    def validate(self, stl_path: Path, config: dict) -> dict:
        stl_path = Path(stl_path)
        if not stl_path.exists():
            return {"valid": False, "error": "File does not exist", "n_triangles": 0}
        size = stl_path.stat().st_size
        if size <= 84:
            return {"valid": False, "error": f"File too small ({size} B)", "n_triangles": 0}
        try:
            data = stl_path.read_bytes()
            n_tri = struct.unpack("<I", data[80:84])[0]
        except Exception as e:
            return {"valid": False, "error": f"Cannot read header: {e}", "n_triangles": 0}
        if n_tri < 10:
            return {"valid": False, "error": f"Too few triangles ({n_tri})", "n_triangles": n_tri}
        expected = 84 + n_tri * 50
        size_ok = abs(size - expected) < 1024
        return {
            "valid": size_ok,
            "n_triangles": n_tri,
            "file_size": size,
            "expected_size": expected,
            "error": None if size_ok else f"Size mismatch: {size} vs {expected}",
        }


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
        size_mm    = SIZE_MM.get(size_key, 75.0)
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

        cfg = {
            "total_height":  TOTAL_HEIGHT_MM,
            "base_thick":    BASE_THICK_MM,
            "wall_thick":    WALL_THICK_MM,
            "cutting_edge":  CUTTING_EDGE_MM,
            "relief_height": RELIEF_HEIGHT_MM,
        }

        if self.mode == "openscad":
            n_tri = self._generate_via_openscad(contours, product_type, size_mm, slug, stl_path)
        elif product_type == "stamp":
            n_tri = self.stl_writer.generate_stamp_stl(main_contour, cfg, stl_path)
        else:
            n_tri = self.stl_writer.generate_cutter_stl(main_contour, cfg, stl_path)

        result = self.validator.validate(stl_path, cfg)
        result["stl_path"]    = str(stl_path)
        result["n_triangles"] = n_tri
        return result

    def generate_all(self, slug: str, product_type: str, source_dir: Path, output_dir: Path) -> dict:
        source_dir = Path(source_dir)
        output_dir = Path(output_dir)
        sizes_result = {}

        for size_key in SIZE_MM:
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
                ["openscad", "-o", str(stl_path), scad_path],
                capture_output=True, timeout=120, check=True,
            )
        finally:
            pathlib.Path(scad_path).unlink(missing_ok=True)
        if stl_path.exists() and stl_path.stat().st_size > 84:
            data = stl_path.read_bytes()
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
