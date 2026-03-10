"""
orchestrator.py - łączy TrendAgent i ListingAgent w jeden pipeline.

Funkcja run_pipeline() prowadzi produkt od tematu do gotowego listingu
i zapisuje listing.json + meta.json w data/products/{slug}/.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agents import trend_agent, listing_agent

log = logging.getLogger(__name__)
console = Console()

DATA_DIR = Path(__file__).parents[2] / "data" / "products"


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
    product_dir = DATA_DIR / slug
    product_dir.mkdir(parents=True, exist_ok=True)

    listing_file = product_dir / "listing.json"
    listing_file.write_text(json.dumps(listing, indent=2, ensure_ascii=False))
    log.info("Saved listing.json → %s", listing_file)

    meta = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "topic": topic,
        "product_type": product_type,
        "size": size,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_file = product_dir / "meta.json"
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    log.info("Saved meta.json → %s", meta_file)

    # ── 4. Podsumowanie w konsoli ────────────────────────────────────────────
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Klucz", style="dim", min_width=16)
    table.add_column("Wartość")

    table.add_row("Slug", f"[bold]{slug}[/bold]")
    table.add_row("Tytuł", listing.get("title", "–"))
    table.add_row("Cena", f"[green]{listing.get('price_suggestion', '–')} EUR[/green]")
    table.add_row("Tagów", str(len(listing.get("tags", []))))
    table.add_row("Status", "[yellow]draft[/yellow]")
    table.add_row("Pliki", f"{listing_file}\n{meta_file}")

    console.print(Panel(table, title="[bold green]Pipeline zakończony[/bold green]", expand=False))

    return {
        "slug": slug,
        "title": listing.get("title"),
        "price_suggestion": listing.get("price_suggestion"),
        "tags": listing.get("tags", []),
        "status": "draft",
    }
