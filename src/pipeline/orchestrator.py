"""
orchestrator.py - łączy TrendAgent i ListingAgent w jeden pipeline.

Funkcja run_pipeline() prowadzi produkt od tematu do gotowego listingu
i zapisuje listing.json + meta.json w data/products/{slug}/.
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
from src.agents.model_agent import create_model_agent
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
    product_dir = ensure_product_dir(slug)

    listing_path = save_listing(slug, listing)
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
    meta_path = save_meta(slug, meta)
    log.info("Saved meta.json → %s", meta_path)

    # ── 4. Design (SVG) ──────────────────────────────────────────────────────
    design_result = {"success": False, "files": [], "mode": "skipped"}
    model_result  = {"sizes": {}}
    stl_files: list[str] = []

    with console.status("[bold green]Generuję SVG (DesignAgent)...[/bold green]"):
        try:
            design_agent = create_design_agent("auto")
            design_result = design_agent.generate(
                topic=topic,
                product_type=product_type,
                sizes=["S", "M", "L"],
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
                source_dir = Path(design_result["files"][0]["path"]).parent
                models_dir = product_dir / "models"
                model_agent = create_model_agent("auto")
                model_result = model_agent.generate_all(
                    slug=slug,
                    product_type=product_type,
                    source_dir=source_dir,
                    output_dir=models_dir,
                )
                stl_files = [
                    str(v["stl_path"])
                    for v in model_result.get("sizes", {}).values()
                    if v.get("valid") and v.get("stl_path")
                ]
                log.info("ModelAgent: sizes=%s  stl_files=%d",
                         list(model_result["sizes"].keys()), len(stl_files))
            except Exception as exc:
                log.warning("ModelAgent failed: %s", exc)
                model_result = {"sizes": {}, "error": str(exc)}

    # ── 6. Render (obrazy produktowe) ─────────────────────────────────────────
    models_ok = len(stl_files) > 0
    design_ok = design_result.get("success", False)

    render_result: dict = {"success": False, "renders": [], "render_dir": ""}
    if models_ok:
        with console.status("[bold green]Generuję renders (RenderAgent)...[/bold green]"):
            try:
                from src.agents.render_agent import create_render_agent
                render_agent = create_render_agent()
                render_result = render_agent.generate(
                    product_dir=product_dir,
                    slug=slug,
                    topic=topic,
                    product_type=product_type,
                )
                log.info("RenderAgent: success=%s renders=%d",
                         render_result.get("success"), len(render_result.get("renders", [])))
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
    render_count = len(render_result.get("renders", []))
    table.add_row("Renders", f"[{'green' if render_ok else 'red'}]{render_count} plików[/]")
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
