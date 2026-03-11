"""
test_svg_stl_batch.py — testuje generację SVG+STL dla istniejących produktów.

Uruchomienie:
  .venv/bin/python scripts/test_svg_stl_batch.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.table import Table
from rich import box

from src.agents.model_agent import create_model_agent
from src.utils.product_io import DATA_DIR

console = Console()

PRODUCTS_DIR = DATA_DIR / "cutter"
AGENT = create_model_agent("pure_python")


def test_product(slug: str, limit: int = 2) -> dict:
    """Testuje generację STL dla produktu. Przetwarza max `limit` rozmiarów SVG."""
    source_dir = PRODUCTS_DIR / slug / "source"
    models_dir = PRODUCTS_DIR / slug / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    svgs = sorted(source_dir.glob("*.svg")) if source_dir.exists() else []
    if not svgs:
        return {"slug": slug, "svgs": 0, "stls": 0, "ok": 0, "fail": 0,
                "error": "brak SVG", "volume": None, "time_s": 0.0}

    results = []
    t0 = time.time()
    for svg_path in svgs[:limit]:
        size_key = svg_path.stem.upper()  # S.svg → S, M.svg → M, L.svg → L
        r = AGENT.generate(
            svg_path=svg_path,
            product_type="cutter",
            size_key=size_key,
            output_dir=models_dir,
        )
        results.append(r)

    elapsed = time.time() - t0
    ok   = sum(1 for r in results if r.get("valid"))
    fail = len(results) - ok
    vols = [r.get("volume_mm3") for r in results if r.get("volume_mm3")]
    avg_vol = sum(vols) / len(vols) if vols else None
    errors  = [r.get("error") for r in results if r.get("error")]

    return {
        "slug":    slug,
        "svgs":    len(svgs),
        "stls":    len(results),
        "ok":      ok,
        "fail":    fail,
        "error":   errors[0] if errors else None,
        "volume":  avg_vol,
        "time_s":  elapsed,
        "watertight": all(r.get("watertight", False) for r in results if r.get("valid")),
        "n_tri":   results[0].get("n_triangles", 0) if results else 0,
    }


def main():
    slugs = sorted(d.name for d in PRODUCTS_DIR.iterdir() if d.is_dir())
    console.print(f"\n[bold cyan]Test SVG→STL[/bold cyan]: {len(slugs)} produktów\n")

    rows = []
    for slug in slugs:
        console.print(f"  [dim]→[/dim] [yellow]{slug}[/yellow]...", end=" ")
        result = test_product(slug)
        status = "[green]OK[/green]" if result["fail"] == 0 and result["ok"] > 0 else "[red]FAIL[/red]"
        console.print(status)
        rows.append(result)

    # Tabela wyników
    table = Table(title="\nWyniki generacji STL", box=box.ROUNDED, show_lines=False)
    table.add_column("Slug",       style="cyan",   no_wrap=True,  max_width=22)
    table.add_column("SVG",        justify="center")
    table.add_column("STL gen.",   justify="center")
    table.add_column("OK",         justify="center")
    table.add_column("Watertight", justify="center")
    table.add_column("Trójkąty",   justify="right")
    table.add_column("Vol. mm³",   justify="right")
    table.add_column("Czas [s]",   justify="right")
    table.add_column("Błąd",       style="red",    max_width=28)

    ok_total = fail_total = 0
    for r in rows:
        wt  = "[green]✓[/green]" if r.get("watertight") else ("[red]✗[/red]" if r["ok"] > 0 else "—")
        vol = f"{r['volume']:.0f}" if r["volume"] else "—"
        err = r["error"] or ""
        status_ok = r["ok"] > 0 and r["fail"] == 0

        table.add_row(
            r["slug"],
            str(r["svgs"]),
            str(r["stls"]),
            f"[green]{r['ok']}[/green]" if r["ok"] else f"[red]{r['ok']}[/red]",
            wt,
            str(r["n_tri"]),
            vol,
            f"{r['time_s']:.2f}",
            err[:28],
        )
        ok_total   += r["ok"]
        fail_total += r["fail"]

    console.print(table)
    console.print(f"\n[bold]Podsumowanie:[/bold] "
                  f"[green]{ok_total} STL OK[/green] / "
                  f"[red]{fail_total} FAIL[/red] "
                  f"z {len(rows)} produktów\n")

    if fail_total > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
