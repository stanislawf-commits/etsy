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

    # -- renders
    renders_dir  = base / "renders"
    render_files = list(renders_dir.glob("*.jpg")) if renders_dir.exists() else []
    if render_files:
        console.print(f"  [green]✓[/green] Renders:  {renders_dir} ({len(render_files)} pliki)")
    else:
        console.print(f"  [yellow]![/yellow] Renders:  brak plikow w {renders_dir}")

    # -- status
    status_color = "green" if status in ("ready_for_publish", "ready_for_render") else "yellow"
    console.print(f"  Status:   [{status_color}]{status}[/{status_color}]")

    if status not in ("ready_for_render", "ready_for_publish"):
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

    # Szukaj meta.json w podfolderach (nowy format) oraz *.json wprost (stary)
    meta_files = sorted(DATA_DIR.glob("*/meta.json"))
    flat_files  = [f for f in sorted(DATA_DIR.glob("*.json"))
                   if not (DATA_DIR / f.stem).is_dir()]
    all_files   = meta_files + flat_files

    if not all_files:
        console.print("[dim]Brak produktow.[/dim]")
        return

    STATUS_COLORS = {
        "ready_for_publish":       "green",
        "ready_for_render":        "cyan",
        "listed":                  "bold green",
        "ready_for_manual_publish": "cyan",
        "draft":                   "yellow",
        "design_error":            "red",
        "model_error":             "red",
    }

    table = Table(title="Produkty etsy3d", show_header=True, header_style="bold cyan")
    table.add_column("Slug", style="dim")
    table.add_column("Tytuł")
    table.add_column("Cena", justify="right")
    table.add_column("SVG", justify="center")
    table.add_column("STL", justify="center")
    table.add_column("Renders", justify="center")
    table.add_column("Status")

    count = 0
    for meta_f in all_files:
        data = json.loads(meta_f.read_text())
        prod_status = data.get("status", "draft")
        if status_filter and prod_status != status_filter:
            continue

        slug     = data.get("slug", meta_f.parent.name)
        prod_dir = DATA_DIR / slug

        # Tytuł z listing.json
        title = "–"
        price = "–"
        listing_path = prod_dir / "listing.json"
        if listing_path.exists():
            try:
                lst   = json.loads(listing_path.read_text())
                title = lst.get("title", "–")[:55]
                price = f"{lst.get('price_suggestion', '–')} EUR"
            except Exception:
                pass

        svg_count = len(list((prod_dir / "source").glob("*.svg"))) if (prod_dir / "source").exists() else 0
        stl_count = len(list((prod_dir / "models").glob("*.stl"))) if (prod_dir / "models").exists() else 0
        rnd_count = len(list((prod_dir / "renders").glob("*.jpg"))) if (prod_dir / "renders").exists() else 0

        color = STATUS_COLORS.get(prod_status, "white")
        table.add_row(
            slug,
            title,
            price,
            str(svg_count) if svg_count else "[dim]0[/dim]",
            str(stl_count) if stl_count else "[dim]0[/dim]",
            str(rnd_count) if rnd_count else "[dim]0[/dim]",
            f"[{color}]{prod_status}[/{color}]",
        )
        count += 1

    console.print(table)
    console.print(f"\nLacznie: [bold]{count}[/bold] produktow")


@cli.command("open-product")
@click.argument("slug")
def open_product(slug):
    """Otwiera folder produktu i wypisuje listing_export.json do terminala."""
    import subprocess

    product_dir = DATA_DIR / slug
    if not product_dir.exists():
        console.print(f"[red]Produkt '{slug}' nie istnieje w {DATA_DIR}[/red]")
        sys.exit(1)

    export_path = product_dir / "listing_export.json"

    # Jeśli brak listing_export.json — wygeneruj dry-run
    if not export_path.exists():
        listing_path = product_dir / "listing.json"
        if not listing_path.exists():
            console.print(f"[red]Brak listing.json w {product_dir}[/red]")
            sys.exit(1)
        from src.agents.etsy_agent import create_etsy_agent
        agent = create_etsy_agent()
        agent.publish(product_dir=product_dir, slug=slug)

    # Odczytaj eksport
    try:
        data = json.loads(export_path.read_text())
    except Exception as exc:
        console.print(f"[red]Błąd odczytu listing_export.json: {exc}[/red]")
        sys.exit(1)

    checklist = data.get("manual_publish_checklist", {})
    renders_path = checklist.get("renders_path", str(product_dir / "renders"))
    tags = data.get("tags", [])

    console.print()
    console.print("[bold cyan]=== LISTING READY TO PUBLISH ===[/bold cyan]")
    console.print(f"  [bold]Tytuł:[/bold]  {data.get('title', '–')}")
    console.print(f"  [bold]Cena:[/bold]   [green]{data.get('price', '–')} EUR[/green]")
    console.print(f"  [bold]Tagi:[/bold]   {', '.join(tags)}")
    console.print()
    console.print("  [bold]Renders[/bold] (uploaduj w tej kolejności):")
    for i, name in enumerate(["hero.jpg", "lifestyle.jpg", "sizes.jpg", "detail.jpg", "info.jpg"], 1):
        exists = (product_dir / "renders" / name).exists()
        mark   = "[green]✓[/green]" if exists else "[red]✗[/red]"
        console.print(f"    {mark} {i}. renders/{name}")
    console.print()
    console.print(f"  [bold]Pełny eksport:[/bold] [dim]{export_path.resolve()}[/dim]")
    console.print()

    # Otwórz folder w menedżerze plików
    try:
        subprocess.Popen(["xdg-open", str(product_dir.resolve())])
        console.print(f"[dim]Otwarto folder: {product_dir.resolve()}[/dim]")
    except Exception as exc:
        console.print(f"[dim yellow]Nie można otworzyć menedżera plików: {exc}[/dim yellow]")


@cli.command("etsy-auth")
def etsy_auth():
    """Uruchamia OAuth2 flow Etsy i zapisuje ETSY_ACCESS_TOKEN do .env."""
    import webbrowser
    from src.agents.etsy_agent import EtsyAgent

    api_key = os.getenv("ETSY_API_KEY", "")
    if not api_key:
        console.print("[bold red]Brak ETSY_API_KEY w .env — ustaw klucz i sprobuj ponownie.[/bold red]")
        sys.exit(1)

    auth_url, code_verifier, state = EtsyAgent.build_auth_url()

    console.print("\n[bold]Etsy OAuth2 — autoryzacja sklepu[/bold]\n")
    console.print("Otwieram przeglądarkę z URL autoryzacji...")
    console.print(f"[dim]{auth_url}[/dim]\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        console.print("[yellow]Nie można otworzyć przeglądarki — skopiuj URL ręcznie.[/yellow]")

    console.print("Po autoryzacji Etsy przekieruje Cię na:")
    console.print(f"  [cyan]http://localhost:3003/callback?code=...&state={state}[/cyan]")
    console.print()

    code = click.prompt("Wklej parametr 'code' z URL callbacku").strip()
    if not code:
        console.print("[red]Brak kodu — anulowano.[/red]")
        sys.exit(1)

    try:
        tokens = EtsyAgent.exchange_code(code, code_verifier)
    except Exception as exc:
        console.print(f"[bold red]Błąd wymiany tokenu:[/bold red] {exc}")
        sys.exit(1)

    access_token  = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    if not access_token:
        console.print("[red]Brak access_token w odpowiedzi Etsy.[/red]")
        sys.exit(1)

    # Zapisz token do .env
    env_path = Path(__file__).parent / ".env"
    env_text = env_path.read_text() if env_path.exists() else ""

    def _set_env_var(text: str, key: str, value: str) -> str:
        import re
        pattern = rf"^{re.escape(key)}=.*$"
        line    = f"{key}={value}"
        if re.search(pattern, text, re.MULTILINE):
            return re.sub(pattern, line, text, flags=re.MULTILINE)
        return text.rstrip("\n") + f"\n{line}\n"

    env_text = _set_env_var(env_text, "ETSY_ACCESS_TOKEN",  access_token)
    if refresh_token:
        env_text = _set_env_var(env_text, "ETSY_REFRESH_TOKEN", refresh_token)

    env_path.write_text(env_text)
    console.print(f"\n[bold green]✓ Token zapisany do {env_path}[/bold green]")
    console.print("Możesz teraz uruchomić: [cyan]python cli.py publish <slug>[/cyan]")


@cli.command("publish")
@click.argument("slug")
def publish_product(slug):
    """Publikuje produkt na Etsy (lub dry-run gdy brak klucza API)."""
    from src.agents.etsy_agent import create_etsy_agent

    product_dir = DATA_DIR / slug
    if not product_dir.exists():
        console.print(f"[red]Produkt '{slug}' nie istnieje w {DATA_DIR}[/red]")
        sys.exit(1)

    agent  = create_etsy_agent()
    result = agent.publish(product_dir=product_dir, slug=slug)

    if result.get("dry_run"):
        export_path = result.get("export_path", "")
        console.print(f"\n[bold yellow]DRY RUN — listing_export.json zapisany[/bold yellow]")
        console.print(f"  [dim]{export_path}[/dim]")
        console.print("\nUzupełnij ETSY_API_KEY w .env i uruchom ponownie,")
        console.print("lub skopiuj dane z listing_export.json ręcznie na Etsy.\n")
        return

    if result.get("error") == "oauth_required":
        console.print("\n[bold yellow]⚠ Brak tokenu OAuth2.[/bold yellow]")
        console.print("Uruchom:  [cyan]python3 cli.py etsy-auth[/cyan]")
        sys.exit(1)

    if not result.get("success"):
        console.print(f"\n[bold red]Błąd publikacji:[/bold red] {result.get('error')}")
        sys.exit(1)

    listing_id  = result.get("listing_id")
    listing_url = result.get("url")
    images      = result.get("images", 0)

    console.print(f"\n[bold green]✓ Opublikowano na Etsy![/bold green]")
    console.print(f"  Listing ID: [bold]{listing_id}[/bold]")
    console.print(f"  URL:        [cyan]{listing_url}[/cyan]")
    console.print(f"  Zdjęcia:    {images}/5")
    console.print(f"\n[dim]Status w meta.json: listed[/dim]\n")


if __name__ == "__main__":
    cli()
