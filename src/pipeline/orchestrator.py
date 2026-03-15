"""
orchestrator.py - łączy TrendAgent i ListingAgent w jeden pipeline.

Funkcja run_pipeline() prowadzi produkt od tematu do gotowego listingu
i zapisuje listing.json + meta.json w data/products/{slug}/.

Funkcja run_pipeline_type_b() obsługuje Typ B (standardowa baza Shapely):
    - design_agent.generate_type_b() → SVG podglądy
    - model_agent.generate_type_b() × N rozmiarów → STL pliki
    - meta.json z polami: product_subtype="B", base_shape, stamp_topic
"""
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agents import trend_agent, listing_agent
from src.agents.design_agent import create_design_agent
from src.agents.model_agent import create_model_agent, _size_mm_map
from src.utils.printability_validator import validate_svg
from src.utils.product_io import DATA_DIR, ensure_product_dir, save_meta, save_listing

log = logging.getLogger(__name__)
console = Console()


def run_pipeline(
    topic: str | None = None,
    product_type: str = "cutter",
    size: str = "M",
) -> dict:
    """
    Uruchamia pełny pipeline: trend → listing → zapis plików.

    Args:
        topic:        Temat produktu. Jeśli None, pobierany z TrendAgent.
        product_type: Typ produktu: "cutter" | "stamp" | "set"
        size:         Rozmiar: "XS" | "S" | "M" | "L" | "XL"

    Returns:
        dict z kluczami: slug, title, price_suggestion, tags, status
    """
    # ── 1. Wybór tematu ──────────────────────────────────────────────────────
    if topic is None:
        console.print("[dim]Brak tematu – pytam TrendAgent o sugestię...[/dim]")
        suggestions = trend_agent.suggest()
        topic = suggestions[0]["topic"]
        console.print(f"[cyan]TrendAgent wybrał:[/cyan] [bold]{topic}[/bold]")

    console.print(
        f"\n[bold]Pipeline start:[/bold] topic=[cyan]{topic}[/cyan]"
        f"  type=[cyan]{product_type}[/cyan]  size=[cyan]{size}[/cyan]\n"
    )

    # ── 2. Generowanie listingu ──────────────────────────────────────────────
    with console.status("[bold green]Generuję listing (Claude API)...[/bold green]"):
        listing = listing_agent.generate(topic, product_type, size)

    slug = listing["slug"]

    # ── 3. Zapis plików ──────────────────────────────────────────────────────
    # Ścieżka: data/products/{product_type}/{slug}/
    product_dir = ensure_product_dir(slug, product_type)

    listing_path = save_listing(slug, listing, product_type=product_type)
    log.info("Saved listing.json → %s", listing_path)

    meta = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "topic": topic,
        "product_type": product_type,
        "size": size,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = save_meta(slug, meta, product_type=product_type)
    log.info("Saved meta.json → %s", meta_path)

    # ── 4. Design (SVG) ──────────────────────────────────────────────────────
    design_result = {"success": False, "files": [], "mode": "skipped"}
    model_result  = {"sizes": {}}
    stl_files: list[str] = []

    with console.status("[bold green]Generuję SVG (DesignAgent)...[/bold green]"):
        try:
            from src.utils.config_loader import cfg as _cfg
            _pt_cfg   = _cfg("product_types").get(product_type, _cfg("product_types").get("cutter", {}))
            all_sizes = list(_pt_cfg.get("sizes", {}).keys()) or ["S", "M", "L"]
            design_agent = create_design_agent("auto")
            design_result = design_agent.generate(
                topic=topic,
                product_type=product_type,
                sizes=all_sizes,
                output_dir=DATA_DIR,
                slug=slug,
            )
            log.info("DesignAgent: success=%s mode=%s files=%d",
                     design_result.get("success"), design_result.get("mode"),
                     len(design_result.get("files", [])))
        except Exception as exc:
            log.warning("DesignAgent failed: %s", exc)
            design_result = {"success": False, "files": [], "mode": "error", "error": str(exc)}

    # ── 5. Model (STL) ────────────────────────────────────────────────────────
    if design_result.get("success") and design_result.get("files"):
        with console.status("[bold green]Generuję STL (ModelAgent)...[/bold green]"):
            try:
                from src.utils.config_loader import cfg as _cfg
                size_map = _cfg("product_types").get(product_type, _cfg("product_types").get("cutter", {})).get("sizes", {})

                source_dir = Path(design_result["files"][0]["path"]).parent

                # Walidacja SVG przed generowaniem STL
                for file_entry in design_result.get("files", []):
                    svg_path = Path(file_entry["path"])
                    size_key = file_entry.get("size", "M")
                    size_mm = float(size_map.get(size_key, {}).get("width_mm", 75))
                    vr = validate_svg(svg_path, size_mm)
                    if vr.errors:
                        log.warning("SVG validation errors [%s %s]: %s",
                                    slug, size_key, "; ".join(vr.errors))
                    if vr.warnings:
                        log.info("SVG validation warnings [%s %s]: %s",
                                 slug, size_key, "; ".join(vr.warnings))

                models_dir = product_dir / "models"
                model_agent = create_model_agent("auto")
                model_result = model_agent.generate_all(
                    slug=slug,
                    source_dir=source_dir,
                    output_dir=models_dir,
                )
                stl_files = model_result.get("stl_files", [])
                log.info("ModelAgent: sizes=%s  stl_files=%d",
                         list(model_result["sizes"].keys()), len(stl_files))
            except Exception as exc:
                log.warning("ModelAgent failed: %s", exc)
                model_result = {"sizes": {}, "stl_files": [], "error": str(exc)}

    # ── 6. Render (obrazy produktowe) ─────────────────────────────────────────
    models_ok = len(stl_files) > 0
    design_ok = design_result.get("success", False)

    render_result: dict = {"success": False, "renders": [], "render_dir": ""}
    if models_ok:
        with console.status("[bold green]Generuję renders (BlenderRenderAgent)...[/bold green]"):
            try:
                from src.agents.blender_render_agent import create_blender_render_agent
                render_agent = create_blender_render_agent()
                render_result = render_agent.generate(
                    product_dir=product_dir,
                    slug=slug,
                    topic=topic,
                    product_type=product_type,
                )
                engine = render_result.get("engine", "?")
                log.info("RenderAgent: success=%s renders=%d engine=%s",
                         render_result.get("success"), len(render_result.get("renders", [])), engine)
            except Exception as exc:
                log.warning("RenderAgent failed: %s", exc)
                render_result = {"success": False, "renders": [], "render_dir": "", "error": str(exc)}

    # ── 7. Aktualizacja meta.json ─────────────────────────────────────────────
    render_ok = render_result.get("success", False)
    pipeline_status = (
        "ready_for_publish" if (design_ok and models_ok and render_ok) else
        "ready_for_render"  if (design_ok and models_ok) else
        "design_error"      if not design_ok else
        "model_error"
    )

    meta["design"] = {"mode": design_result.get("mode"), "success": design_ok}
    meta["models"] = {
        "success": models_ok,
        "sizes": list(model_result.get("sizes", {}).keys()),
        "stl_count": len(stl_files),
    }
    meta["renders"] = {"success": render_ok, "count": len(render_result.get("renders", []))}
    meta["status"] = pipeline_status
    save_meta(slug, meta)
    log.info("Updated meta.json → status=%s", pipeline_status)

    # ── 8. Podsumowanie w konsoli ─────────────────────────────────────────────
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Klucz", style="dim", min_width=16)
    table.add_column("Wartość")

    table.add_row("Slug",    f"[bold]{slug}[/bold]")
    table.add_row("Tytuł",   listing.get("title", "–"))
    table.add_row("Cena",    f"[green]{listing.get('price_suggestion', '–')} EUR[/green]")
    table.add_row("Tagów",   str(len(listing.get("tags", []))))
    svg_count = len(design_result.get("files", []))
    table.add_row("SVG",     f"[{'green' if design_ok else 'red'}]{svg_count} plików[/]"
                             f"  (mode: {design_result.get('mode', '?')})")
    table.add_row("STL",     f"[{'green' if models_ok else 'red'}]{len(stl_files)} plików[/]")
    render_count  = len(render_result.get("renders", []))
    render_engine = render_result.get("engine", "pillow")
    table.add_row("Renders", f"[{'green' if render_ok else 'red'}]{render_count} plików[/]"
                             f"  (engine: {render_engine})")
    status_color = "green" if pipeline_status == "ready_for_publish" else "yellow"
    table.add_row("Status",  f"[{status_color}]{pipeline_status}[/{status_color}]")

    console.print(Panel(table, title="[bold green]Pipeline zakończony[/bold green]", expand=False))

    return {
        "slug":             slug,
        "title":            listing.get("title"),
        "price_suggestion": listing.get("price_suggestion"),
        "tags":             listing.get("tags", []),
        "status":           pipeline_status,
        "design":           design_result,
        "models":           model_result,
        "stl_files":        stl_files,
        "renders":          render_result,
    }


# ── Typ B pipeline ────────────────────────────────────────────────────────────

_DEFAULT_SIZES_B = ["S", "M", "L"]


def run_pipeline_type_b(
    topic: str | None = None,
    base_shape: str = "heart",
    sizes: list[str] | None = None,
    stamp_topic: str | None = None,
    product_type: str = "cutter",
) -> dict:
    """
    Pipeline Typ B — standardowa baza Shapely.

    Schemat meta.json:
        product_subtype: "B"
        base_shape:      np. "heart"
        stamp_topic:     opcjonalny temat wzoru stempla (tylko dla stamp)

    Args:
        topic:        Temat listingu. Jeśli None — TrendAgent dobierze.
        base_shape:   Nazwa kształtu bazy (z config/base_shapes.yaml).
        sizes:        Lista rozmiarów (default ["S","M","L"]).
        stamp_topic:  Opcjonalny temat wzoru stempla.
        product_type: "cutter" | "stamp" (stamp wymaga stamp_topic).

    Returns:
        dict z kluczami: slug, title, price_suggestion, tags, status, stl_files
    """
    from src.shapes.base_shapes import get_base
    from shapely import affinity

    sizes = sizes or _DEFAULT_SIZES_B
    size_map = {k: v for k, v in _size_mm_map().items() if k in sizes}

    # ── 1. Temat ─────────────────────────────────────────────────────────────
    if topic is None:
        suggestions = trend_agent.suggest()
        topic = suggestions[0]["topic"]
        console.print(f"[cyan]TrendAgent wybrał:[/cyan] [bold]{topic}[/bold]")

    console.print(
        f"\n[bold]Pipeline Typ B:[/bold] topic=[cyan]{topic}[/cyan]"
        f"  base=[cyan]{base_shape}[/cyan]  sizes=[cyan]{','.join(sizes)}[/cyan]\n"
    )

    # ── 2. Listing ────────────────────────────────────────────────────────────
    with console.status("[bold green]Generuję listing (Claude API)...[/bold green]"):
        listing = listing_agent.generate(topic, product_type, "M")

    slug = listing["slug"]
    product_dir = ensure_product_dir(slug, product_type)

    save_listing(slug, listing, product_type=product_type)

    meta = {
        "id":              str(uuid.uuid4()),
        "slug":            slug,
        "topic":           topic,
        "product_type":    product_type,
        "product_subtype": "B",
        "base_shape":      base_shape,
        "stamp_topic":     stamp_topic,
        "status":          "draft",
        "created_at":      datetime.now(timezone.utc).isoformat(),
    }
    save_meta(slug, meta, product_type=product_type)

    # ── 3. Design (SVG podglądy) ──────────────────────────────────────────────
    design_result: dict = {"success": False, "files": [], "mode": "skipped"}
    with console.status("[bold green]Generuję SVG (DesignAgent Typ B)...[/bold green]"):
        try:
            design_agent = create_design_agent("auto")
            design_result = design_agent.generate_type_b(
                product={"base_shape": base_shape, "slug": slug},
                output_dir=DATA_DIR / product_type,
                sizes=sizes,
            )
            log.info("DesignAgent Typ B: success=%s files=%d",
                     design_result.get("success"), len(design_result.get("files", [])))
        except Exception as exc:
            log.warning("DesignAgent Typ B failed: %s", exc)
            design_result = {"success": False, "files": [], "mode": "error", "error": str(exc)}

    # ── 4. Model (STL) ────────────────────────────────────────────────────────
    stl_files: list[str] = []
    size_results: dict   = {}

    with console.status("[bold green]Generuję STL (ModelAgent Typ B)...[/bold green]"):
        try:
            model_agent = create_model_agent("auto")
            ref_mm      = size_map.get("M") or next(iter(size_map.values()))
            base_poly   = get_base(base_shape, ref_mm)
            models_dir  = product_dir / "models"
            models_dir.mkdir(parents=True, exist_ok=True)

            for size_key, size_mm in size_map.items():
                sc = size_mm / ref_mm
                poly = affinity.scale(base_poly, xfact=sc, yfact=sc, origin=(0, 0))
                r = model_agent.generate_type_b(
                    base_poly=poly,
                    size_mm=size_mm,
                    product_type=product_type,
                    output_dir=models_dir,
                    size_key=size_key,
                )
                size_results[size_key] = r
                if r.get("valid") and r.get("stl_path"):
                    stl_files.append(r["stl_path"])
                    log.info("STL OK: %s  n_tri=%s", r["stl_path"], r.get("n_triangles"))
                else:
                    log.warning("STL failed: size=%s error=%s", size_key, r.get("error"))
        except Exception as exc:
            log.warning("ModelAgent Typ B failed: %s", exc)

    # ── 5. Aktualizacja meta.json ─────────────────────────────────────────────
    design_ok = design_result.get("success", False)
    models_ok = len(stl_files) > 0

    pipeline_status = (
        "ready_for_render" if (design_ok and models_ok) else
        "design_error"     if not design_ok else
        "model_error"
    )

    meta["design"] = {"mode": "shapely", "success": design_ok}
    meta["models"] = {
        "success":   models_ok,
        "sizes":     list(size_results.keys()),
        "stl_count": len(stl_files),
    }
    meta["status"] = pipeline_status
    save_meta(slug, meta, product_type=product_type)

    # ── 6. Podsumowanie ───────────────────────────────────────────────────────
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Klucz", style="dim", min_width=16)
    table.add_column("Wartość")

    table.add_row("Slug",       f"[bold]{slug}[/bold]")
    table.add_row("Tytuł",      listing.get("title", "–"))
    table.add_row("Cena",       f"[green]{listing.get('price_suggestion', '–')} EUR[/green]")
    table.add_row("Baza",       f"[cyan]{base_shape}[/cyan]")
    table.add_row("Rozmiary",   ", ".join(sizes))
    svg_n = len(design_result.get("files", []))
    table.add_row("SVG",        f"[{'green' if design_ok else 'red'}]{svg_n} plików[/]")
    table.add_row("STL",        f"[{'green' if models_ok else 'red'}]{len(stl_files)} plików[/]")
    sc = "green" if pipeline_status == "ready_for_render" else "yellow"
    table.add_row("Status",     f"[{sc}]{pipeline_status}[/{sc}]")

    console.print(Panel(table, title="[bold green]Pipeline Typ B — zakończony[/bold green]", expand=False))

    return {
        "slug":             slug,
        "title":            listing.get("title"),
        "price_suggestion": listing.get("price_suggestion"),
        "tags":             listing.get("tags", []),
        "status":           pipeline_status,
        "design":           design_result,
        "stl_files":        stl_files,
        "sizes":            size_results,
    }
