"""
model_agent.py — konwertuje Shapely Polygon → STL (Typ B pipeline).

Tryby:
  openscad    - generuje .scad i wywołuje openscad CLI (via src.shapes.scad_export)
  pure_python - bezpośredni zapis binarnego STL (własna triangulacja)
  auto        - openscad jeśli dostępny, inaczej pure_python

Interfejs Typ B:
  agent = create_model_agent('auto')
  result = agent.generate_type_b(base_poly, size_mm, product_type, output_dir)

Uruchomienie standalone:
  python3 src/agents/model_agent.py
"""

import logging
import math
import struct
import subprocess
from pathlib import Path

from src.utils.config_loader import cfg

log = logging.getLogger(__name__)


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
    """Główny agent: Shapely Polygon → STL (Typ B pipeline)."""

    def __init__(self, config: dict = None):
        self.config     = config or {}
        self.mode       = self._detect_mode()
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

    def generate_type_b(
        self,
        base_poly,
        size_mm: float,
        product_type: str,
        output_dir: Path,
        size_key: str = "",
        stamp_poly=None,
    ) -> dict:
        """
        Generuje STL dla produktu Typ B z Shapely Polygon.

        Args:
            base_poly:    Shapely Polygon bazy (z get_base())
            size_mm:      Wymiar w mm
            product_type: 'cutter' | 'stamp'
            output_dir:   Katalog wyjściowy STL
            size_key:     Opcjonalny klucz rozmiaru (S/M/L/XL) — do nazwy pliku
            stamp_poly:   Shapely Polygon wzoru stempla (wymagany gdy product_type='stamp')

        Returns:
            {'stl_path': str, 'valid': bool, 'n_triangles': int, 'size_mm': float, ...}
        """
        from src.shapes.scad_export import cutter_scad, stamp_scad, run_openscad

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        prefix = f"{size_key}_" if size_key else ""
        stl_path = output_dir / f"{prefix}{product_type}.stl"

        model_cfg = self._stl_cfg_for_pure_python()

        if self.mode == "openscad":
            if product_type == "stamp":
                if stamp_poly is None:
                    return {"stl_path": None, "valid": False, "n_triangles": 0,
                            "error": "stamp_poly required for product_type='stamp'"}
                scad = stamp_scad(base_poly, stamp_poly, size_mm)
            else:
                scad = cutter_scad(base_poly, size_mm)
            ok = run_openscad(scad, stl_path)
            if not ok:
                return {"stl_path": None, "valid": False, "n_triangles": 0,
                        "error": "OpenSCAD failed — check openscad CLI"}
            n_tri = self._count_stl_triangles(stl_path)
        else:
            contour = list(base_poly.exterior.coords)[:-1]
            if product_type == "stamp":
                if stamp_poly is None:
                    return {"stl_path": None, "valid": False, "n_triangles": 0,
                            "error": "stamp_poly required for product_type='stamp'"}
                stamp_contour = list(stamp_poly.exterior.coords)[:-1]
                n_tri = self.stl_writer.generate_stamp_stl(stamp_contour, model_cfg, stl_path)
            else:
                n_tri = self.stl_writer.generate_cutter_stl(contour, model_cfg, stl_path)

        result = self.validator.validate(stl_path, model_cfg)
        result["stl_path"]    = str(stl_path)
        result["n_triangles"] = n_tri
        result["size_mm"]     = size_mm
        return result

    def generate_type_b_all(
        self,
        base_poly,
        slug: str,
        output_dir: Path,
        sizes: dict[str, float] | None = None,
        product_type: str | None = None,
        stamp_poly=None,
    ) -> dict:
        """
        Generuje STL dla wszystkich rozmiarów (Typ B).

        Args:
            base_poly:    Shapely Polygon bazy (zostanie przeskalowany do każdego rozmiaru)
            slug:         Slug produktu
            output_dir:   Katalog bazowy (slug/stl/ zostanie utworzony)
            sizes:        {size_key: size_mm} — domyślnie z product_types.yaml
            product_type: 'cutter' | 'stamp' | None (obydwa)
            stamp_poly:   Wymagany gdy product_type='stamp'
        """
        from src.shapes.base_shapes import get_base
        from src.shapes import affinity  # noqa — sprawdzamy dostępność

        sizes = sizes or _size_mm_map()
        ptypes = [product_type] if product_type else ["cutter"]
        stl_dir = Path(output_dir) / slug / "stl"

        sizes_result: dict = {}
        all_stl_files: list[str] = []

        for size_key, size_mm in sizes.items():
            # Przeskaluj polygon do konkretnego rozmiaru
            # Wyznaczamy nazwę kształtu z pierwotnego poly — używamy jego bounding box
            from shapely import affinity as _aff
            b = base_poly.bounds
            current_size = max(b[2] - b[0], b[3] - b[1])
            if current_size > 1e-9:
                sc = size_mm / current_size
                scaled_poly = _aff.scale(base_poly, xfact=sc, yfact=sc, origin=(0, 0))
            else:
                scaled_poly = base_poly

            sizes_result[size_key] = {}
            for ptype in ptypes:
                r = self.generate_type_b(
                    scaled_poly, size_mm, ptype, stl_dir,
                    size_key=size_key, stamp_poly=stamp_poly
                )
                sizes_result[size_key][ptype] = r
                if r.get("valid") and r.get("stl_path"):
                    all_stl_files.append(r["stl_path"])
                log.info("[%s/%s] %s  tri=%s",
                         size_key, ptype,
                         "OK" if r.get("valid") else "FAIL",
                         r.get("n_triangles", 0))

        return {"slug": slug, "stl_files": all_stl_files, "sizes": sizes_result}

    def _stl_cfg_for_pure_python(self) -> dict:
        """Mapuje stl_defaults (base_shapes.yaml) na klucze PurePythonSTLWriter."""
        d = cfg("base_shapes").get("stl_defaults", {})
        return {
            "total_height":  d.get("total_height_mm",   TOTAL_HEIGHT_MM),
            "base_thick":    d.get("base_thick_mm",      BASE_THICK_MM),
            "wall_thick":    d.get("wall_thick_mm",      WALL_THICK_MM),
            "cutting_edge":  d.get("cutting_edge_mm",    CUTTING_EDGE_MM),
            "relief_height": d.get("relief_height_mm",   RELIEF_HEIGHT_MM),
            "taper_height":  d.get("taper_height_mm",    3.0),
        }

    def _count_stl_triangles(self, stl_path: Path) -> int:
        if not stl_path.exists() or stl_path.stat().st_size < 84:
            return 0
        data = stl_path.read_bytes()
        if data[:5].lower() == b"solid":
            return data.decode("ascii", errors="replace").count("facet normal")
        return struct.unpack("<I", data[80:84])[0]


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

    from src.shapes.base_shapes import get_base

    DATA_DIR = Path(__file__).parents[2] / "data" / "products"
    slug     = "heart-test"
    poly     = get_base("heart", 75.0)

    print(f"\nModelAgent Typ B standalone test — {slug}")
    agent  = create_model_agent("pure_python")
    result = agent.generate_type_b(
        base_poly=poly,
        size_mm=75.0,
        product_type="cutter",
        output_dir=DATA_DIR / slug / "stl",
        size_key="M",
    )
    status = "OK" if result.get("valid") else "FAIL"
    print(f"  [{status}] triangles={result.get('n_triangles',0)}  {result.get('stl_path','-')}")
    if result.get("error"):
        print(f"  ERROR: {result['error']}")
