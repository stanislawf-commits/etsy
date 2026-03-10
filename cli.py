"""
etsy3d CLI - zarządzanie pipelinem produktów Etsy z drukiem 3D.
"""
import os
import sys
import json
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import print as rprint

load_dotenv()
console = Console()

DATA_DIR = Path(__file__).parent / "data" / "products"


@click.group()
def cli():
    """etsy3d - automatyczny pipeline dla sklepu Etsy z produktami 3D."""
    pass


@cli.command()
def health():
    """Sprawdza konfigurację i połączenia z API."""
    console.print("[bold]Sprawdzanie konfiguracji etsy3d...[/bold]\n")

    checks = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
        "ETSY_API_KEY": os.getenv("ETSY_API_KEY"),
        "ETSY_API_SECRET": os.getenv("ETSY_API_SECRET"),
        "ETSY_SHOP_ID": os.getenv("ETSY_SHOP_ID"),
    }

    table = Table(title="Stan konfiguracji", show_header=True, header_style="bold cyan")
    table.add_column("Zmienna", style="dim")
    table.add_column("Status")

    all_ok = True
    for key, value in checks.items():
        if value:
            table.add_row(key, "[green]OK[/green]")
        else:
            table.add_row(key, "[red]BRAK[/red]")
            all_ok = False

    console.print(table)

    if all_ok:
        console.print("\n[bold green]Wszystkie klucze skonfigurowane.[/bold green]")
    else:
        console.print("\n[bold yellow]Uzupelnij brakujace klucze w pliku .env[/bold yellow]")
        sys.exit(1)


@cli.command("new-product")
@click.argument("name", required=False, default=None)
@click.option("--type", "-t", "product_type", default="cutter", show_default=True,
              help="Typ produktu: cutter | stamp | set")
@click.option("--size", "-s", default="M", show_default=True,
              help="Rozmiar: XS | S | M | L | XL")
def new_product(name, product_type, size):
    """Tworzy nowy produkt przez pelny pipeline (listing + SVG + STL).

    NAME to temat produktu (opcjonalne - jesli pominienty, TrendAgent dobierze temat).
    """
    from src.pipeline.orchestrator import run_pipeline

    try:
        result = run_pipeline(topic=name, product_type=product_type, size=size)
    except Exception as e:
        console.print(f"[bold red]Blad pipeline:[/bold red] {e}")
        sys.exit(1)

    slug   = result.get("slug", "?")
    status = result.get("status", "unknown")
    base   = DATA_DIR / slug

    # -- listing
    listing_path = base / "listing.json"
    if listing_path.exists():
        console.print(f"  [green]✓[/green] Listing:  {listing_path}")
    else:
        console.print(f"  [yellow]![/yellow] Listing:  brak")

    # -- SVG
    source_dir = base / "source"
    svg_files  = list(source_dir.glob("*.svg")) if source_dir.exists() else []
    if svg_files:
        console.print(f"  [green]✓[/green] SVG:      {source_dir} ({len(svg_files)} pliki)")
    else:
        console.print(f"  [yellow]![/yellow] SVG:      brak plikow w {source_dir}")

    # -- STL
    models_dir = base / "models"
    stl_files  = list(models_dir.glob("*.stl")) if models_dir.exists() else []
    if stl_files:
        console.print(f"  [green]✓[/green] STL:      {models_dir} ({len(stl_files)} pliki)")
    else:
        console.print(f"  [yellow]![/yellow] STL:      brak plikow w {models_dir}")

    # -- status
    status_color = "green" if status == "ready_for_render" else "yellow"
    console.print(f"  Status:   [{status_color}]{status}[/{status_color}]")

    if status != "ready_for_render":
        sys.exit(1)


@cli.command()
@click.argument("slug", required=False)
def status(slug):
    """Pokazuje status produktu lub wszystkich produktow."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = list(DATA_DIR.glob("*.json"))

    if not files:
        console.print("[dim]Brak produktow. Uzyj: python cli.py new-product <nazwa>[/dim]")
        return

    if slug:
        product_file = DATA_DIR / f"{slug}.json"
        if not product_file.exists():
            console.print(f"[red]Produkt '{slug}' nie istnieje.[/red]")
            sys.exit(1)
        files = [product_file]

    for f in files:
        data = json.loads(f.read_text())
        steps = data.get("steps_completed", [])
        steps_str = ", ".join(steps) if steps else "brak"
        console.print(f"[bold]{data['name']}[/bold] ({data['slug']})")
        console.print(f"  Status:   [cyan]{data['status']}[/cyan]")
        console.print(f"  Kroki:    {steps_str}")
        console.print()


@cli.command("list")
@click.option("--status-filter", "-s", default=None, help="Filtruj po statusie (draft, ready, published)")
def list_products(status_filter):
    """Listuje wszystkie produkty w pipeline."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = list(DATA_DIR.glob("*.json"))

    if not files:
        console.print("[dim]Brak produktow.[/dim]")
        return

    table = Table(title="Produkty etsy3d", show_header=True, header_style="bold cyan")
    table.add_column("Slug", style="dim")
    table.add_column("Nazwa")
    table.add_column("Kategoria")
    table.add_column("Status")
    table.add_column("Kroki")

    count = 0
    for f in sorted(files):
        data = json.loads(f.read_text())
        if status_filter and data.get("status") != status_filter:
            continue
        steps_count = len(data.get("steps_completed", []))
        status_color = {
            "draft": "yellow",
            "ready": "cyan",
            "published": "green",
        }.get(data.get("status", "draft"), "white")

        table.add_row(
            data["slug"],
            data["name"],
            data.get("category", "-"),
            f"[{status_color}]{data.get('status', 'draft')}[/{status_color}]",
            str(steps_count),
        )
        count += 1

    console.print(table)
    console.print(f"\nLacznie: [bold]{count}[/bold] produktow")


if __name__ == "__main__":
    cli()
