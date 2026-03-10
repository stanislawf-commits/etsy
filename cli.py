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
@click.option("--batch", "-b", default=1, type=click.IntRange(1, 50), show_default=True,
              help="Uruchom pipeline N razy (TrendAgent dobiera tematy automatycznie)")
def new_product(name, product_type, size, batch):
    """Tworzy nowy produkt przez pelny pipeline (listing + SVG + STL).

    NAME to temat produktu (opcjonalne - jesli pominienty, TrendAgent dobierze temat).
    Z opcja --batch N uruchamia pipeline N razy bez podawania NAME.
    """
    from src.pipeline.orchestrator import run_pipeline

    if batch > 1 and name:
        console.print("[red]Błąd: --batch nie może być użyty razem z NAME.[/red]")
        console.print("Usuń NAME lub pomiń --batch.")
        sys.exit(1)

    if batch == 1:
        # ── Tryb pojedynczy (istniejące zachowanie) ──
        try:
            result = run_pipeline(topic=name, product_type=product_type, size=size)
        except Exception as e:
            console.print(f"[bold red]Blad pipeline:[/bold red] {e}")
            sys.exit(1)

        slug   = result.get("slug", "?")
        status = result.get("status", "unknown")
        base   = DATA_DIR / slug

        listing_path = base / "listing.json"
        if listing_path.exists():
            console.print(f"  [green]✓[/green] Listing:  {listing_path}")
        else:
            console.print(f"  [yellow]![/yellow] Listing:  brak")

        source_dir = base / "source"
        svg_files  = list(source_dir.glob("*.svg")) if source_dir.exists() else []
        if svg_files:
            console.print(f"  [green]✓[/green] SVG:      {source_dir} ({len(svg_files)} pliki)")
        else:
            console.print(f"  [yellow]![/yellow] SVG:      brak plikow w {source_dir}")

        models_dir = base / "models"
        stl_files  = list(models_dir.glob("*.stl")) if models_dir.exists() else []
        if stl_files:
            console.print(f"  [green]✓[/green] STL:      {models_dir} ({len(stl_files)} pliki)")
        else:
            console.print(f"  [yellow]![/yellow] STL:      brak plikow w {models_dir}")

        renders_dir  = base / "renders"
        render_files = list(renders_dir.glob("*.jpg")) if renders_dir.exists() else []
        if render_files:
            console.print(f"  [green]✓[/green] Renders:  {renders_dir} ({len(render_files)} pliki)")
        else:
            console.print(f"  [yellow]![/yellow] Renders:  brak plikow w {renders_dir}")

        status_color = "green" if status in ("ready_for_publish", "ready_for_render") else "yellow"
        console.print(f"  Status:   [{status_color}]{status}[/{status_color}]")

        if status not in ("ready_for_render", "ready_for_publish"):
            sys.exit(1)

    else:
        # ── Tryb batch ──
        results = []
        for i in range(batch):
            console.rule(f"[bold]Produkt {i + 1}/{batch}[/bold]")
            try:
                r = run_pipeline(topic=None, product_type=product_type, size=size)
                results.append(r)
            except Exception as e:
                console.print(f"[red]Produkt {i + 1} zakończony błędem: {e}[/red]")
                results.append({"slug": "?", "status": "error", "error": str(e)})

        _print_batch_summary(results)


def _print_batch_summary(results: list[dict]) -> None:
    """Wypisuje tabelę podsumowania po uruchomieniu --batch."""
    table = Table(title="Batch — podsumowanie", show_header=True, header_style="bold cyan")
    table.add_column("#",      justify="right", style="dim", width=3)
    table.add_column("Slug",   style="dim")
    table.add_column("Temat")
    table.add_column("Status")
    table.add_column("Cena",   justify="right")
    table.add_column("Błąd",   style="red")

    ok = 0
    for i, r in enumerate(results, 1):
        status_val = r.get("status", "error")
        color = "green" if status_val == "ready_for_publish" else \
                "cyan"  if status_val == "ready_for_render"  else "red"
        price = r.get("price_suggestion") or r.get("price") or "–"
        price_str = f"{price} EUR" if price != "–" else "–"
        table.add_row(
            str(i),
            r.get("slug", "?"),
            (r.get("title") or "")[:45],
            f"[{color}]{status_val}[/{color}]",
            price_str,
            r.get("error", "") or "",
        )
        if status_val not in ("error",):
            ok += 1

    console.print(table)
    console.print(f"\n  Ukończono: [bold green]{ok}[/bold green] / {len(results)}")


@cli.command("analytics-sync")
@click.option("--slug", default=None, help="Synchronizuj tylko ten produkt (domyślnie: wszystkie listed)")
def analytics_sync(slug):
    """Pobiera views + favorites z Etsy API i zapisuje do DB."""
    import os
    from src.db.session import init_db, get_session
    from src.db.models import Product, ListingStats
    from src.utils.etsy_analytics import fetch_listing_stats
    from sqlmodel import select

    access_token = os.getenv("ETSY_ACCESS_TOKEN", "")
    shop_id      = os.getenv("ETSY_SHOP_ID", "")

    if not access_token:
        console.print("[bold red]Brak ETSY_ACCESS_TOKEN.[/bold red] Uruchom: [cyan]python cli.py etsy-auth[/cyan]")
        sys.exit(1)
    if not shop_id:
        console.print("[bold red]Brak ETSY_SHOP_ID w .env.[/bold red]")
        sys.exit(1)

    init_db()

    with get_session() as session:
        query = select(Product).where(Product.etsy_listing_id.isnot(None))
        if slug:
            query = query.where(Product.slug == slug)
        products = session.exec(query).all()
        product_data = [(p.slug, p.etsy_listing_id) for p in products]

    if not product_data:
        console.print("[dim]Brak opublikowanych produktów z etsy_listing_id.[/dim]")
        return

    table = Table(title="Analytics sync", show_header=True, header_style="bold cyan")
    table.add_column("Slug",       style="dim")
    table.add_column("Listing ID", style="dim")
    table.add_column("Views",      justify="right")
    table.add_column("Favorites",  justify="right")
    table.add_column("Status")

    synced = 0
    for p_slug, listing_id in product_data:
        try:
            with console.status(f"[dim]Pobieram stats dla {p_slug}...[/dim]"):
                stats_data = fetch_listing_stats(
                    listing_id,
                    shop_id=shop_id,
                    access_token=access_token,
                )
            with get_session() as session:
                session.add(ListingStats(
                    slug=p_slug,
                    listing_id=listing_id,
                    views=stats_data["views"],
                    favorites=stats_data["favorites"],
                ))
            table.add_row(p_slug, listing_id,
                          str(stats_data["views"]), str(stats_data["favorites"]),
                          "[green]OK[/green]")
            synced += 1
        except Exception as exc:
            table.add_row(p_slug, listing_id, "–", "–", f"[red]{exc}[/red]")

    console.print(table)
    console.print(f"\n  Zsynchronizowano: [bold green]{synced}[/bold green] / {len(product_data)}")


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


@cli.command("stats")
def stats():
    """Statystyki pipeline — liczby produktów, statusy, przychody."""
    from src.db.session import init_db, get_session
    from src.db.models import Product
    from sqlmodel import select, func

    init_db()

    with get_session() as session:
        # model_dump() odłącza dane od sesji — bezpieczne poza kontekstem
        all_products = [p.model_dump() for p in session.exec(select(Product)).all()]

    if not all_products:
        # Fallback: czytaj z JSON jeśli DB pusta
        from src.utils.product_io import load_all_products
        raw = load_all_products()
        all_products = [{
            "slug":         p["slug"],
            "status":       p["meta"].get("status", "draft"),
            "price":        p["listing"].get("price_suggestion"),
            "product_type": p["meta"].get("product_type", "cutter"),
            "render_engine":p["meta"].get("render_engine"),
        } for p in raw]

    # ── Zlicz statusy ──
    status_counts: dict[str, int] = {}
    type_counts:   dict[str, int] = {}
    total_revenue  = 0.0
    blender_count  = 0

    for p in all_products:
        s = p.get("status", "draft") if isinstance(p, dict) else p.status
        status_counts[s] = status_counts.get(s, 0) + 1
        t = p.get("product_type", "cutter") if isinstance(p, dict) else p.product_type
        type_counts[t] = type_counts.get(t, 0) + 1
        price = (p.get("price") if isinstance(p, dict) else p.price)
        if price and s in ("listed", "ready_for_publish"):
            total_revenue += float(price)
        eng = p.get("render_engine") if isinstance(p, dict) else p.render_engine
        if eng == "blender":
            blender_count += 1

    total = len(all_products)

    # ── Tabela statusów ──
    console.print()
    st_table = Table(title="Produkty wg statusu", show_header=True, header_style="bold cyan")
    st_table.add_column("Status",  style="dim")
    st_table.add_column("Liczba",  justify="right")
    st_table.add_column("% całości", justify="right")

    STATUS_COLORS = {
        "ready_for_publish": "green",
        "listed":            "bold green",
        "draft":             "yellow",
        "design_error":      "red",
        "model_error":       "red",
    }
    for status_key, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        color = STATUS_COLORS.get(status_key, "white")
        pct   = f"{count/total*100:.0f}%"
        st_table.add_row(f"[{color}]{status_key}[/{color}]", str(count), pct)
    console.print(st_table)

    # ── Typy produktów ──
    tp_table = Table(title="Typy produktów", show_header=True, header_style="bold cyan")
    tp_table.add_column("Typ",    style="dim")
    tp_table.add_column("Liczba", justify="right")
    for pt, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        tp_table.add_row(pt, str(cnt))
    console.print(tp_table)

    # ── Podsumowanie ──
    console.print()
    console.print(f"  Wszystkich produktów:  [bold]{total}[/bold]")
    console.print(f"  Gotowych do pub:       [green]{status_counts.get('ready_for_publish', 0)}[/green]")
    console.print(f"  Opublikowanych:        [bold green]{status_counts.get('listed', 0)}[/bold green]")
    console.print(f"  Potencjalny przychód:  [bold cyan]{total_revenue:.2f} EUR[/bold cyan]")
    console.print(f"  Blender renders:       {blender_count}/{total}")
    console.print()

    # ── Analytics (ostatnia synchronizacja) ──
    try:
        from src.db.models import ListingStats
        from sqlmodel import select as sa_select

        with get_session() as session:
            all_stats = [
                s.model_dump()
                for s in session.exec(
                    sa_select(ListingStats).order_by(ListingStats.fetched_at.desc())
                ).all()
            ]

        # Najnowszy wiersz per slug
        seen: set[str] = set()
        top: list[dict] = []
        for s in all_stats:
            if s["slug"] not in seen:
                seen.add(s["slug"])
                top.append(s)

        if top:
            an_table = Table(title="Analytics (ostatnia synchronizacja)", show_header=True,
                             header_style="bold cyan")
            an_table.add_column("Slug",      style="dim")
            an_table.add_column("Views",     justify="right")
            an_table.add_column("Favorites", justify="right")
            an_table.add_column("Pobrano",   style="dim")
            for s in sorted(top, key=lambda x: x["views"], reverse=True):
                fetched = str(s["fetched_at"])[:16]
                an_table.add_row(s["slug"], str(s["views"]), str(s["favorites"]), fetched)
            console.print(an_table)
        else:
            console.print("[dim]Brak danych analytics. Uruchom: python cli.py analytics-sync[/dim]")
            console.print()
    except Exception:
        pass  # ListingStats tabela może nie istnieć w starej DB — ignoruj


@cli.command("db-migrate")
@click.option("--dry", is_flag=True, help="Podgląd bez zapisu do DB")
def db_migrate(dry):
    """Migruje produkty z flat JSON do SQLite."""
    from src.db.migrate import migrate

    console.print(f"[bold]Migracja produktów do SQLite{'  (dry run)' if dry else ''}[/bold]\n")
    stats = migrate(dry_run=dry)

    console.print(f"  Migrowanych: [green]{stats['migrated']}[/green]")
    console.print(f"  Błędów:      [{'red' if stats['errors'] else 'dim'}]{stats['errors']}[/]")

    if not dry:
        from src.db.session import DB_PATH
        console.print(f"\n[dim]Baza: {DB_PATH}[/dim]")


if __name__ == "__main__":
    cli()
