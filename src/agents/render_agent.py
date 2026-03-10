"""
render_agent.py — generuje 5 obrazów produktowych JPG 2000×2000 px (Pillow only).

Nie wymaga GPU, Blendera ani cairosvg. Primary source: DALL-E PNG (*_dalle_raw.png).
"""
import json
import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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

CANVAS = 2000

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

        img_m  = self._load_product_image(source_dir, slug, "M")
        renders: list[str] = []

        specs = [
            ("hero",      self._render_hero,      (img_m, slug, topic)),
            ("lifestyle", self._render_lifestyle, (img_m, topic)),
            ("sizes",     self._render_sizes,     (source_dir, slug)),
            ("detail",    self._render_detail,    (img_m,)),
            ("info",      self._render_info,      (img_m, product_dir, slug, topic)),
        ]

        for name, fn, args in specs:
            try:
                result_img = fn(*args)
                out_path = render_dir / f"{name}.jpg"
                result_img.convert("RGB").save(str(out_path), "JPEG", quality=92)
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
        Kolejność: DALL-E PNG → szary placeholder.
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

        log.debug("Using placeholder for %s size=%s", slug, size)
        return self._make_placeholder(slug, size)

    def _make_placeholder(self, slug: str, size: str, px: int = 1400) -> Image.Image:
        img  = Image.new("RGBA", (px, px), (200, 200, 200, 255))
        draw = ImageDraw.Draw(img)
        text = f"{slug}\n[{size}]"
        draw.text(
            (px // 2, px // 2), text,
            fill=(80, 80, 80, 255), font=self._font(48), anchor="mm",
        )
        return img

    # ── IMG 1: hero ────────────────────────────────────────────────────────────

    def _render_hero(self, img: Image.Image, slug: str, topic: str) -> Image.Image:
        canvas = Image.new("RGBA", (CANVAS, CANVAS), COLOR_WHITE)
        draw   = ImageDraw.Draw(canvas)

        prod = self._fit(img, 1400)
        ox = (CANVAS - prod.width)  // 2
        oy = (CANVAS - prod.height) // 2
        canvas.alpha_composite(prod, (ox, oy))

        # Badge prawy górny róg
        badge_text = "Food Safe · 3D Printed"
        bw, bh = 480, 64
        bx, by = CANVAS - bw - 40, 40
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=COLOR_BADGE)
        draw.text(
            (bx + bw // 2, by + bh // 2), badge_text,
            fill=COLOR_WHITE, font=self._font(28), anchor="mm",
        )

        # Nazwa produktu dół center
        draw.text(
            (CANVAS // 2, CANVAS - 80), topic.title(),
            fill=COLOR_BLACK, font=self._font(36), anchor="mm",
        )

        return canvas

    # ── IMG 2: lifestyle ───────────────────────────────────────────────────────

    def _render_lifestyle(self, img: Image.Image, topic: str) -> Image.Image:
        canvas = Image.new("RGBA", (CANVAS, CANVAS), COLOR_CREAM)
        draw   = ImageDraw.Draw(canvas)

        # Losowe kółka "mąka na blacie" (seed=42 → deterministyczne)
        rng = random.Random(42)
        for _ in range(80):
            r  = rng.randint(5, 30)
            cx = rng.randint(0, CANVAS)
            cy = rng.randint(0, CANVAS)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=COLOR_BISCUIT)

        # Cień (paste z offsetem)
        prod   = self._fit(img, 1300)
        shadow = Image.new("RGBA", prod.size, (0, 0, 0, 0))
        sd     = ImageDraw.Draw(shadow)
        sd.rectangle([0, 0, prod.width, prod.height], fill=(0, 0, 0, 60))
        cx = (CANVAS - prod.width)  // 2
        cy = (CANVAS - prod.height) // 2
        canvas.alpha_composite(shadow, (cx + 12, cy + 12))
        canvas.alpha_composite(prod,   (cx,      cy))

        # Prawy dolny tekst
        draw.text(
            (CANVAS - 60, CANVAS - 60), "Baked with Love \u2665",
            fill=COLOR_WARM, font=self._font(30), anchor="rb",
        )

        return canvas

    # ── IMG 3: sizes ───────────────────────────────────────────────────────────

    def _render_sizes(self, source_dir: Path, slug: str) -> Image.Image:
        canvas = Image.new("RGBA", (CANVAS, CANVAS), COLOR_WHITE)
        draw   = ImageDraw.Draw(canvas)

        draw.text(
            (CANVAS // 2, 80), "Available Sizes",
            fill=COLOR_BLACK, font=self._font(48), anchor="mm",
        )

        sizes_info = [
            ("S", 420, "S \u00b7 60mm"),
            ("M", 520, "M \u00b7 75mm"),
            ("L", 620, "L \u00b7 90mm"),
        ]
        col_xs = [340, 1000, 1660]
        img_cy = CANVAS // 2 - 40

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

    def _render_detail(self, img: Image.Image) -> Image.Image:
        canvas = Image.new("RGBA", (CANVAS, CANVAS), COLOR_WHITE)
        draw   = ImageDraw.Draw(canvas)

        prod = self._fit(img, 1600)
        ox = (CANVAS - prod.width)  // 2
        oy = (CANVAS - prod.height) // 2
        canvas.alpha_composite(prod, (ox, oy))

        # Lewa strzałka + opis grubości ścianki
        draw.text(
            (180, CANVAS // 2), "\u2192 1.8mm walls",
            fill=COLOR_RED, font=self._font(32), anchor="lm",
        )

        # Prawy dół
        draw.text(
            (CANVAS - 60, CANVAS - 60), "Food Safe PLA",
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
    ) -> Image.Image:
        canvas = Image.new("RGBA", (CANVAS, CANVAS), COLOR_LIGHT)
        draw   = ImageDraw.Draw(canvas)

        # Produkt po lewej (800×800)
        prod = self._fit(img, 800)
        ox = 80
        oy = (CANVAS - prod.height) // 2
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
        ry = (CANVAS - 700) // 2

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
