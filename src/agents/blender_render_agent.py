"""
blender_render_agent.py — generuje 5 obrazów produktowych używając Blender 4.x.

Pipeline:
  1. Blender headless → realistyczny render 3D (hero, lifestyle, detail, sizes)
  2. Pillow post-processing → text overlay, badge, info panel

Fallback: gdy Blender niedostępny → deleguje do render_agent (Pillow-only).

Użycie:
  agent = create_blender_render_agent()
  result = agent.generate(product_dir, slug, topic, product_type)
"""
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.utils.config_loader import cfg

log = logging.getLogger(__name__)

SCRIPT_DIR   = Path(__file__).parent / "blender_scripts"
RENDER_SCRIPT = SCRIPT_DIR / "render_product.py"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]

# Kolory
COLOR_WHITE  = (255, 255, 255, 255)
COLOR_BLACK  = (30,  30,  30,  255)
COLOR_DARK   = (50,  50,  50,  255)
COLOR_BADGE  = (80,  80,  80,  230)
COLOR_WARM   = (140, 100, 60,  255)
COLOR_RED    = (180, 40,  40,  255)
COLOR_GRAY   = (130, 130, 130, 255)
COLOR_CREAM_BG = (253, 246, 236, 255)


class BlenderRenderAgent:
    def __init__(self):
        self._blender_bin = self._find_blender()
        self._font_path   = self._find_font()
        if self._blender_bin:
            log.info("BlenderRenderAgent: Blender at %s", self._blender_bin)
        else:
            log.warning("BlenderRenderAgent: Blender not found — will use Pillow fallback")

    # ── Publiczne API ──────────────────────────────────────────────────────────

    def generate(
        self,
        product_dir: str | Path,
        slug: str,
        topic: str,
        product_type: str,
    ) -> dict:
        """
        Generuje 5 obrazów JPG do product_dir/renders/.

        Returns:
            {"success": bool, "renders": [paths], "render_dir": str, "engine": str}
        """
        product_dir = Path(product_dir)
        models_dir  = product_dir / "models"
        render_dir  = product_dir / "renders"
        render_dir.mkdir(parents=True, exist_ok=True)

        # Znajdź STL dla rozmiarów S, M, L
        stl_files = self._find_stl_files(models_dir, slug, product_type)

        if not stl_files:
            log.warning("No STL files found in %s — falling back to Pillow", models_dir)
            return self._pillow_fallback(product_dir, slug, topic, product_type)

        if not self._blender_bin:
            return self._pillow_fallback(product_dir, slug, topic, product_type)

        # Pobierz dane listingu
        listing = self._load_listing(product_dir)
        title   = listing.get("title", topic.title())
        price   = listing.get("price_suggestion", "–")
        tags    = listing.get("tags", [])[:5]

        canvas_px = cfg("etsy")["images"]["size_px"]
        renders   = []

        # 1. HERO — 3/4 view M size, white background + badge overlay
        stl_m = stl_files.get("M") or next(iter(stl_files.values()))
        hero_raw = render_dir / "_blender_hero_raw.jpg"
        if self._blender_render(stl_m, hero_raw, mode="hero", res=canvas_px):
            hero_final = render_dir / "hero.jpg"
            self._overlay_hero(hero_raw, hero_final, topic, canvas_px)
            renders.append(str(hero_final))
            hero_raw.unlink(missing_ok=True)
        else:
            log.warning("Blender hero render failed")

        # 2. LIFESTYLE — 3/4 view, cream background + text
        lifestyle_raw = render_dir / "_blender_lifestyle_raw.jpg"
        if self._blender_render(stl_m, lifestyle_raw, mode="lifestyle", res=canvas_px):
            lifestyle_final = render_dir / "lifestyle.jpg"
            self._overlay_lifestyle(lifestyle_raw, lifestyle_final, canvas_px)
            renders.append(str(lifestyle_final))
            lifestyle_raw.unlink(missing_ok=True)
        else:
            log.warning("Blender lifestyle render failed")

        # 3. SIZES — 3 rozmiary obok siebie
        sizes_path = render_dir / "sizes.jpg"
        if self._render_sizes(stl_files, sizes_path, canvas_px):
            renders.append(str(sizes_path))
        else:
            log.warning("Blender sizes render failed")

        # 4. DETAIL — widok z góry + text overlay
        detail_raw = render_dir / "_blender_detail_raw.jpg"
        if self._blender_render(stl_m, detail_raw, mode="detail", res=canvas_px):
            detail_final = render_dir / "detail.jpg"
            self._overlay_detail(detail_raw, detail_final, canvas_px)
            renders.append(str(detail_final))
            detail_raw.unlink(missing_ok=True)
        else:
            log.warning("Blender detail render failed")

        # 5. INFO — hero render + text panel po prawej
        info_path = render_dir / "info.jpg"
        hero_for_info = render_dir / "_blender_hero_raw2.jpg"
        if self._blender_render(stl_m, hero_for_info, mode="hero", res=canvas_px):
            self._overlay_info(hero_for_info, info_path, title, price, tags, canvas_px)
            renders.append(str(info_path))
            hero_for_info.unlink(missing_ok=True)
        else:
            log.warning("Blender info render failed")

        success = len(renders) == 5
        log.info("BlenderRenderAgent: %d/5 renders OK for %s", len(renders), slug)

        if not success and renders:
            # Częściowy sukces — uzupełnij brakujące Pillowem
            log.info("Filling missing renders with Pillow fallback")
            fallback = self._pillow_fallback(product_dir, slug, topic, product_type)
            renders = fallback.get("renders", renders)
            success = len(renders) == 5

        return {
            "success":    success,
            "renders":    renders,
            "render_dir": str(render_dir),
            "engine":     "blender" if self._blender_bin else "pillow",
        }

    # ── Blender wywołanie ──────────────────────────────────────────────────────

    def _blender_render(
        self,
        stl_path: Path,
        output_path: Path,
        mode: str = "hero",
        res: int = 2000,
        title: str = "",
        size_label: str = "",
    ) -> bool:
        """Uruchamia Blender headless i renderuje STL do JPEG. Zwraca True przy sukcesie."""
        cmd = [
            self._blender_bin,
            "--background",
            "--python", str(RENDER_SCRIPT),
            "--",
            "--stl",   str(stl_path),
            "--out",   str(output_path),
            "--mode",  mode,
            "--title", title or "",
            "--size_label", size_label,
            "--res",   str(res),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=120,
                text=True,
            )
            if result.returncode != 0:
                log.warning("Blender error (mode=%s): %s", mode, result.stderr[-500:])
                return False
            if not output_path.exists() or output_path.stat().st_size < 1000:
                log.warning("Blender output missing or too small: %s", output_path)
                return False
            log.debug("Blender render OK: %s (%d B)", output_path.name, output_path.stat().st_size)
            return True
        except subprocess.TimeoutExpired:
            log.warning("Blender timeout (mode=%s, stl=%s)", mode, stl_path.name)
            return False
        except Exception as exc:
            log.warning("Blender exception: %s", exc)
            return False

    # ── Sizes render ───────────────────────────────────────────────────────────

    def _render_sizes(self, stl_files: dict, output_path: Path, canvas_px: int) -> bool:
        """Renderuje S, M, L obok siebie na jednym obrazie."""
        sizes_cfg = cfg("product_types").get("cutter", {}).get("sizes", {})
        size_order = [("S", int(canvas_px * 0.26)), ("M", int(canvas_px * 0.33)),
                      ("L", int(canvas_px * 0.40))]
        raw_renders: dict[str, Path] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            for size_key, _ in size_order:
                stl = stl_files.get(size_key)
                if not stl:
                    continue
                raw = tmpdir / f"size_{size_key}.jpg"
                mm  = sizes_cfg.get(size_key, {}).get("width_mm", 75)
                if self._blender_render(stl, raw, mode="sizes_item",
                                        res=800, size_label=f"{size_key} · {mm}mm"):
                    raw_renders[size_key] = raw

            if not raw_renders:
                return False

            canvas = Image.new("RGBA", (canvas_px, canvas_px), (255, 255, 255, 255))
            draw   = ImageDraw.Draw(canvas)

            draw.text((canvas_px // 2, 80), "Available Sizes",
                      fill=COLOR_BLACK, font=self._font(52), anchor="mm")

            col_positions = {
                "S": canvas_px // 6,
                "M": canvas_px // 2,
                "L": canvas_px * 5 // 6,
            }
            img_cy = int(canvas_px * 0.52)

            for size_key, target_px in size_order:
                raw = raw_renders.get(size_key)
                if not raw:
                    continue
                prod = Image.open(raw).convert("RGBA")
                prod.thumbnail((target_px, target_px), Image.LANCZOS)
                col_x = col_positions[size_key]
                ox = col_x - prod.width  // 2
                oy = img_cy - prod.height // 2
                canvas.alpha_composite(prod, (max(0, ox), max(0, oy)))
                mm = sizes_cfg.get(size_key, {}).get("width_mm", "?")
                draw.text((col_x, img_cy + prod.height // 2 + 50),
                          f"{size_key} · {mm}mm",
                          fill=COLOR_GRAY, font=self._font(32), anchor="mm")

        canvas.convert("RGB").save(str(output_path), "JPEG", quality=92)
        return True

    # ── Pillow overlays ────────────────────────────────────────────────────────

    def _overlay_hero(self, raw: Path, out: Path, topic: str, canvas_px: int) -> None:
        img  = Image.open(raw).convert("RGBA")
        draw = ImageDraw.Draw(img)

        # Badge "Food Safe · 3D Printed" — prawy górny róg
        badge_text = "Food Safe · 3D Printed"
        bw = int(canvas_px * 0.28)
        bh = 68
        bx = canvas_px - bw - 40
        by = 40
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill=COLOR_BADGE)
        draw.text((bx + bw // 2, by + bh // 2), badge_text,
                  fill=COLOR_WHITE, font=self._font(28), anchor="mm")

        # Nazwa produktu — dół środek
        draw.text((canvas_px // 2, canvas_px - 70), topic.title(),
                  fill=COLOR_BLACK, font=self._font(40), anchor="mm")

        img.convert("RGB").save(str(out), "JPEG", quality=92)

    def _overlay_lifestyle(self, raw: Path, out: Path, canvas_px: int) -> None:
        img  = Image.open(raw).convert("RGBA")
        draw = ImageDraw.Draw(img)
        draw.text((canvas_px - 60, canvas_px - 60), "Baked with Love ♥",
                  fill=COLOR_WARM, font=self._font(32), anchor="rb")
        img.convert("RGB").save(str(out), "JPEG", quality=92)

    def _overlay_detail(self, raw: Path, out: Path, canvas_px: int) -> None:
        img  = Image.open(raw).convert("RGBA")
        draw = ImageDraw.Draw(img)
        wall = cfg("product_types").get("cutter", {}).get("wall_thickness", 1.8)
        draw.text((200, canvas_px // 2), f"→ {wall}mm walls",
                  fill=COLOR_RED, font=self._font(38), anchor="lm")
        draw.text((canvas_px - 60, canvas_px - 60), "Food Safe PLA",
                  fill=COLOR_GRAY, font=self._font(30), anchor="rb")
        img.convert("RGB").save(str(out), "JPEG", quality=92)

    def _overlay_info(
        self, raw: Path, out: Path,
        title: str, price, tags: list, canvas_px: int,
    ) -> None:
        bg   = Image.new("RGBA", (canvas_px, canvas_px), (245, 245, 245, 255))
        prod = Image.open(raw).convert("RGBA")

        # Produkt po lewej
        max_w = int(canvas_px * 0.48)
        prod.thumbnail((max_w, max_w), Image.LANCZOS)
        ox = 60
        oy = (canvas_px - prod.height) // 2
        bg.alpha_composite(prod, (ox, oy))

        draw = ImageDraw.Draw(bg)
        rx = ox + prod.width + 80
        ry = (canvas_px - 700) // 2

        short_title = title[:60] + "…" if len(title) > 60 else title
        draw.text((rx, ry), short_title, fill=COLOR_DARK, font=self._font(36), anchor="lt")
        ry += 90
        draw.text((rx, ry), f"Price: {price} EUR",
                  fill=COLOR_WARM, font=self._font(38), anchor="lt")
        ry += 80
        draw.text((rx, ry), "Keywords:", fill=COLOR_GRAY, font=self._font(28), anchor="lt")
        ry += 50
        for tag in tags:
            draw.text((rx + 20, ry), f"• {tag}", fill=COLOR_DARK, font=self._font(27), anchor="lt")
            ry += 48

        bg.convert("RGB").save(str(out), "JPEG", quality=92)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _find_stl_files(self, models_dir: Path, slug: str, product_type: str) -> dict[str, Path]:
        """Szuka plików STL dla rozmiarów S, M, L. Zwraca {size: Path}."""
        if not models_dir.exists():
            return {}
        result = {}
        for size_key in ["S", "M", "L", "XS", "XL"]:
            candidates = [
                models_dir / f"{slug}_{size_key}_{product_type}.stl",
                models_dir / f"{slug}-{size_key}_{size_key}_{product_type}.stl",
                models_dir / f"{slug}-{size_key.lower()}_{size_key}_{product_type}.stl",
            ]
            # Dodaj każdy znaleziony STL z size_key w nazwie
            for f in models_dir.glob(f"*{size_key}*{product_type}*.stl"):
                candidates.append(f)
            found = next((p for p in candidates if p.exists()), None)
            if found:
                result[size_key] = found
        return result

    def _load_listing(self, product_dir: Path) -> dict:
        listing_path = product_dir / "listing.json"
        if listing_path.exists():
            try:
                return json.loads(listing_path.read_text())
            except Exception:
                pass
        return {}

    def _find_font(self) -> str | None:
        for path in FONT_PATHS:
            if Path(path).exists():
                return path
        return None

    def _find_blender(self) -> str | None:
        """Szuka blendera w PATH i typowych lokalizacjach."""
        import shutil
        candidates = ["blender", "blender3", "/usr/bin/blender", "/snap/bin/blender"]
        for c in candidates:
            path = shutil.which(c) or (c if Path(c).exists() else None)
            if path:
                return path
        return None

    def _font(self, size: int):
        for path in FONT_PATHS:
            if Path(path).exists():
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass
        return ImageFont.load_default()

    def _pillow_fallback(self, product_dir, slug, topic, product_type) -> dict:
        """Deleguje do oryginalnego render_agent (Pillow-only)."""
        from src.agents.render_agent import create_render_agent
        log.info("Using Pillow fallback for %s", slug)
        agent = create_render_agent()
        result = agent.generate(
            product_dir=product_dir,
            slug=slug,
            topic=topic,
            product_type=product_type,
        )
        result["engine"] = "pillow"
        return result


# ── Factory ────────────────────────────────────────────────────────────────────

def create_blender_render_agent() -> BlenderRenderAgent:
    return BlenderRenderAgent()
