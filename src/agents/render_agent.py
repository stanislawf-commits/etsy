"""
render_agent.py — generuje obrazy produktowe JPG (Pillow only).

Parametry (rozmiar, jakość, kolejność) z config/etsy.yaml.
Nie wymaga GPU, Blendera ani cairosvg. Primary source: DALL-E PNG (*_dalle_raw.png).
"""
import json
import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.utils.config_loader import cfg

log = logging.getLogger(__name__)

# ── Stałe kolorów ─────────────────────────────────────────────────────────────
COLOR_WHITE   = "#FFFFFF"
COLOR_CREAM   = "#FDF6EC"
COLOR_LIGHT   = "#F5F5F5"
COLOR_BLACK   = "#000000"
COLOR_GRAY    = "#888888"
COLOR_DARK    = "#333333"
COLOR_BADGE   = "#555555"
COLOR_WARM    = "#8B7355"
COLOR_RED     = "#CC2222"
COLOR_BISCUIT = "#F0E6D3"

def _canvas_size() -> int:
    return cfg("etsy").get("images", {}).get("size_px", 2000)

def _jpeg_quality() -> int:
    return cfg("etsy").get("images", {}).get("quality", 92)

def _upload_order() -> list[str]:
    return cfg("etsy").get("images", {}).get("upload_order", ["hero","lifestyle","sizes","detail","info"])

CANVAS = 2000  # backwards-compat alias, runtime wartość z cfg

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


class RenderAgent:
    def __init__(self, config=None):
        self.config = config or {}
        self._font_path: str | None = None
        self._load_fonts()

    # ── Publiczne API ──────────────────────────────────────────────────────────

    def generate(
        self,
        product_dir: str | Path,
        slug: str,
        topic: str,
        product_type: str,
    ) -> dict:
        """
        Generuje 5 obrazów JPG 2000×2000 do katalogu product_dir/renders/.
        Zwraca: {'success': bool, 'renders': [path...], 'render_dir': str}
        """
        product_dir = Path(product_dir)
        source_dir  = product_dir / "source"
        render_dir  = product_dir / "renders"
        render_dir.mkdir(parents=True, exist_ok=True)

        canvas_px = _canvas_size()
        quality   = _jpeg_quality()
        order     = _upload_order()

        img_m  = self._load_product_image(source_dir, slug, "M")
        renders: list[str] = []

        render_map = {
            "hero":      (self._render_hero,      (img_m, slug, topic, canvas_px)),
            "lifestyle": (self._render_lifestyle, (img_m, topic, canvas_px)),
            "sizes":     (self._render_sizes,     (source_dir, slug, product_type, canvas_px)),
            "detail":    (self._render_detail,    (img_m, product_type, canvas_px)),
            "info":      (self._render_info,      (img_m, product_dir, slug, topic, canvas_px)),
        }

        for name in order:
            if name not in render_map:
                log.warning("Unknown render type in upload_order: %r", name)
                continue
            fn, args = render_map[name]
            try:
                result_img = fn(*args)
                out_path = render_dir / f"{name}.jpg"
                result_img.convert("RGB").save(str(out_path), "JPEG", quality=quality)
                renders.append(str(out_path))
                log.info("Render saved: %s", out_path)
            except Exception as exc:
                log.warning("Render '%s' failed: %s", name, exc, exc_info=True)

        success = len(renders) == 5
        log.info("RenderAgent: %d/5 renders generated for %s", len(renders), slug)
        return {"success": success, "renders": renders, "render_dir": str(render_dir)}

    # ── Ładowanie obrazu produktu ──────────────────────────────────────────────

    def _load_product_image(
        self, source_dir: Path, slug: str, size: str = "M"
    ) -> Image.Image:
        """
        Kolejność: DALL-E PNG → szary placeholder z informacją o SVG.
        Zwraca RGBA.
        """
        dalle_path = source_dir / f"{slug}-{size}_dalle_raw.png"
        if dalle_path.exists():
            try:
                img = Image.open(dalle_path).convert("RGBA")
                log.debug("Loaded DALL-E PNG: %s", dalle_path)
                return img
            except Exception as exc:
                log.warning("Cannot open DALL-E PNG %s: %s", dalle_path, exc)

        # Sprawdź czy istnieje SVG (Sprint 2+ naming: {SIZE}.svg)
        svg_path = source_dir / f"{size}.svg"
        has_svg = svg_path.exists()
        log.debug("Using placeholder for %s size=%s (svg=%s)", slug, size, has_svg)
        return self._make_placeholder(slug, size, has_svg=has_svg)

    def _make_placeholder(self, slug: str, size: str, px: int = 1400,
                          has_svg: bool = False) -> Image.Image:
        bg_color = (220, 235, 245, 255) if has_svg else (200, 200, 200, 255)
        img  = Image.new("RGBA", (px, px), bg_color)
        draw = ImageDraw.Draw(img)
        label = f"{size}.svg" if has_svg else f"{slug}\n[{size}]"
        draw.text(
            (px // 2, px // 2), label,
            fill=(60, 80, 100, 255) if has_svg else (80, 80, 80, 255),
            font=self._font(52 if has_svg else 48), anchor="mm",
        )
        if has_svg:
            draw.text(
                (px // 2, px // 2 + 80), "SVG ready · use Blender for 3D render",
                fill=(100, 120, 140, 255), font=self._font(28), anchor="mm",
            )
        return img

    # ── IMG 1: hero ────────────────────────────────────────────────────────────

    def _render_hero(self, img: Image.Image, slug: str, topic: str, canvas_px: int = 2000) -> Image.Image:
        canvas = Image.new("RGBA", (canvas_px, canvas_px), COLOR_WHITE)
        draw   = ImageDraw.Draw(canvas)

        prod = self._fit(img, int(canvas_px * 0.70))
        ox = (canvas_px - prod.width)  // 2
        oy = (canvas_px - prod.height) // 2
        canvas.alpha_composite(prod, (ox, oy))

        # Badge prawy górny róg
        badge_text = "Food Safe · 3D Printed"
        bw, bh = int(canvas_px * 0.24), 64
        bx, by = canvas_px - bw - 40, 40
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=COLOR_BADGE)
        draw.text(
            (bx + bw // 2, by + bh // 2), badge_text,
            fill=COLOR_WHITE, font=self._font(28), anchor="mm",
        )

        # Nazwa produktu dół center
        draw.text(
            (canvas_px // 2, canvas_px - 80), topic.title(),
            fill=COLOR_BLACK, font=self._font(36), anchor="mm",
        )

        return canvas

    # ── IMG 2: lifestyle ───────────────────────────────────────────────────────

    def _render_lifestyle(self, img: Image.Image, topic: str, canvas_px: int = 2000) -> Image.Image:
        canvas = Image.new("RGBA", (canvas_px, canvas_px), COLOR_CREAM)
        draw   = ImageDraw.Draw(canvas)

        # Losowe kółka "mąka na blacie" (seed=42 → deterministyczne)
        rng = random.Random(42)
        for _ in range(80):
            r  = rng.randint(5, 30)
            cx = rng.randint(0, canvas_px)
            cy = rng.randint(0, canvas_px)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOR_BISCUIT)

        # Cień (paste z offsetem)
        prod   = self._fit(img, int(canvas_px * 0.65))
        shadow = Image.new("RGBA", prod.size, (0, 0, 0, 0))
        sd     = ImageDraw.Draw(shadow)
        sd.rectangle([0, 0, prod.width, prod.height], fill=(0, 0, 0, 60))
        cx = (canvas_px - prod.width)  // 2
        cy = (canvas_px - prod.height) // 2
        canvas.alpha_composite(shadow, (cx + 12, cy + 12))
        canvas.alpha_composite(prod,   (cx,      cy))

        # Prawy dolny tekst
        draw.text(
            (canvas_px - 60, canvas_px - 60), "Baked with Love \u2665",
            fill=COLOR_WARM, font=self._font(30), anchor="rb",
        )

        return canvas

    # ── IMG 3: sizes ───────────────────────────────────────────────────────────

    def _render_sizes(self, source_dir: Path, slug: str, product_type: str = "cutter",
                      canvas_px: int = 2000) -> Image.Image:
        canvas = Image.new("RGBA", (canvas_px, canvas_px), COLOR_WHITE)
        draw   = ImageDraw.Draw(canvas)

        draw.text(
            (canvas_px // 2, 80), "Available Sizes",
            fill=COLOR_BLACK, font=self._font(48), anchor="mm",
        )

        # Pobierz rozmiary z config
        from src.utils.config_loader import cfg as _cfg
        pt_cfg   = _cfg("product_types")
        sizes_cfg = pt_cfg.get(product_type, pt_cfg.get("cutter", {})).get("sizes", {})
        sizes_info = [
            ("S", int(canvas_px * 0.21), f"S · {sizes_cfg.get('S', {}).get('width_mm', 60)}mm"),
            ("M", int(canvas_px * 0.26), f"M · {sizes_cfg.get('M', {}).get('width_mm', 75)}mm"),
            ("L", int(canvas_px * 0.31), f"L · {sizes_cfg.get('L', {}).get('width_mm', 90)}mm"),
        ]
        col_xs = [canvas_px // 6, canvas_px // 2, canvas_px * 5 // 6]
        img_cy = canvas_px // 2 - 40

        for (size_key, px, label), col_x in zip(sizes_info, col_xs):
            prod_img = self._load_product_image(source_dir, slug, size_key)
            prod     = self._fit(prod_img, px)
            ox = col_x - prod.width  // 2
            oy = img_cy - prod.height // 2
            canvas.alpha_composite(prod, (ox, oy))
            draw.text(
                (col_x, img_cy + prod.height // 2 + 40), label,
                fill=COLOR_GRAY, font=self._font(28), anchor="mm",
            )

        return canvas

    # ── IMG 4: detail ──────────────────────────────────────────────────────────

    def _render_detail(self, img: Image.Image, product_type: str = "cutter",
                       canvas_px: int = 2000) -> Image.Image:
        canvas = Image.new("RGBA", (canvas_px, canvas_px), COLOR_WHITE)
        draw   = ImageDraw.Draw(canvas)

        prod = self._fit(img, int(canvas_px * 0.80))
        ox = (canvas_px - prod.width)  // 2
        oy = (canvas_px - prod.height) // 2
        canvas.alpha_composite(prod, (ox, oy))

        # Pobierz parametry z config zależnie od typu
        from src.utils.config_loader import cfg as _cfg
        pt_cfg = _cfg("product_types").get(product_type, _cfg("product_types").get("cutter", {}))
        if product_type == "stamp":
            base_h   = pt_cfg.get("base_height", 3.0)
            relief_h = pt_cfg.get("relief_height", 2.0)
            detail_line  = f"\u2192 {base_h}mm base + {relief_h}mm relief"
            bottom_label = "PLA / PETG"
        else:
            wall = pt_cfg.get("wall_thickness", 1.8)
            detail_line  = f"\u2192 {wall}mm walls"
            bottom_label = "Food Safe PLA"

        draw.text(
            (180, canvas_px // 2), detail_line,
            fill=COLOR_RED, font=self._font(32), anchor="lm",
        )
        draw.text(
            (canvas_px - 60, canvas_px - 60), bottom_label,
            fill=COLOR_GRAY, font=self._font(28), anchor="rb",
        )

        return canvas

    # ── IMG 5: info ────────────────────────────────────────────────────────────

    def _render_info(
        self,
        img: Image.Image,
        product_dir: Path,
        slug: str,
        topic: str,
        canvas_px: int = 2000,
    ) -> Image.Image:
        canvas = Image.new("RGBA", (canvas_px, canvas_px), COLOR_LIGHT)
        draw   = ImageDraw.Draw(canvas)

        # Produkt po lewej
        prod = self._fit(img, int(canvas_px * 0.40))
        ox = 80
        oy = (canvas_px - prod.height) // 2
        canvas.alpha_composite(prod, (ox, oy))

        # Dane z listing.json
        title_text = topic.title()
        price_text = "–"
        tags: list[str] = []
        listing_path = product_dir / "listing.json"
        if listing_path.exists():
            try:
                data       = json.loads(listing_path.read_text())
                title_text = data.get("title", title_text)
                price_text = str(data.get("price_suggestion", "–"))
                tags       = data.get("tags", [])[:5]
            except Exception:
                pass

        # Prawa kolumna
        rx = ox + prod.width + 80
        ry = (canvas_px - 700) // 2

        # Tytuł może być długi — wstępnie ucinamy do 60 znaków
        short_title = title_text if len(title_text) <= 60 else title_text[:57] + "…"
        draw.text((rx, ry), short_title, fill=COLOR_DARK, font=self._font(36), anchor="lt")
        ry += 80

        draw.text((rx, ry), f"Price: {price_text} EUR",
                  fill=COLOR_WARM, font=self._font(34), anchor="lt")
        ry += 70

        draw.text((rx, ry), "Tags:", fill=COLOR_GRAY, font=self._font(28), anchor="lt")
        ry += 50

        for tag in tags:
            draw.text((rx + 20, ry), f"\u2022 {tag}",
                      fill=COLOR_DARK, font=self._font(26), anchor="lt")
            ry += 46

        return canvas

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _fit(self, img: Image.Image, max_px: int) -> Image.Image:
        """Skaluje obraz zachowując proporcje, max dim = max_px."""
        w, h  = img.size
        scale = min(max_px / w, max_px / h)
        nw    = max(1, int(w * scale))
        nh    = max(1, int(h * scale))
        return img.resize((nw, nh), Image.LANCZOS).convert("RGBA")

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if self._font_path:
            try:
                return ImageFont.truetype(self._font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _load_fonts(self) -> None:
        for path in FONT_PATHS:
            if Path(path).exists():
                self._font_path = path
                log.debug("Loaded font: %s", path)
                return
        log.debug("No TrueType font found — using PIL default")


# ── Factory ────────────────────────────────────────────────────────────────────

def create_render_agent(config=None) -> RenderAgent:
    return RenderAgent(config)


# ── Standalone test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    slug = "floral-wreath-cutter-m"
    root = Path(__file__).parents[2]
    product_dir = root / "data" / "products" / slug

    if not product_dir.exists():
        print(f"ERROR: {product_dir} nie istnieje", file=sys.stderr)
        sys.exit(1)

    agent  = create_render_agent()
    result = agent.generate(
        product_dir=product_dir,
        slug=slug,
        topic="floral wreath",
        product_type="cutter",
    )

    print(f"Success: {result['success']}")
    print(f"Renders ({len(result['renders'])}):")
    for p in result["renders"]:
        print(f"  {p}")
