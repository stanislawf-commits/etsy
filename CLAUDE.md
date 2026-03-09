# etsy3d - Opis projektu dla Claude Code

## Cel projektu

Automatyczny pipeline do tworzenia i publikowania produktów drukowanych w 3D
w sklepie Etsy. Claude (Anthropic API) generuje opisy, tytuły, tagi SEO i
strategie cenowe. Pipeline prowadzi nowy produkt od szkicu (draft) do
opublikowania (published).

## Architektura

```
cli.py                  # punkt wejscia CLI (click)
src/
  agents/               # agenci Claude do generowania tresci
  pipeline/             # kroki pipeline (draft -> review -> publish)
  utils/                # pomocnicze funkcje (Etsy API, pliki, logi)
config/                 # konfiguracja YAML (kategorie, cenniki, szablony)
data/
  products/             # pliki JSON z danymi produktow (jeden plik = jeden produkt)
  templates/            # szablony promptow dla agentow
logs/                   # logi dzialan pipeline
docs/                   # dokumentacja
tests/                  # testy jednostkowe i integracyjne
```

## Technologie

- **Python 3.11+**
- **anthropic** - Claude API (generowanie tresci, SEO, ceny)
- **openai** - DALL-E (generowanie grafik mockup, opcjonalnie)
- **click** - CLI
- **rich** - sformatowane wyjscie w terminalu
- **requests** - Etsy API v3
- **python-dotenv** - zmienne srodowiskowe
- **pillow** - obrobka obrazow
- **svgwrite** - generowanie grafik wektorowych SVG

## Zasady pracy

### Kod

- Python 3.11+, type hints tam gdzie pomaga czytelnosci
- Brak nadmiarowych abstrakcji — jeden plik = jeden agent lub jeden krok
- Nie uzywac klas jesli wystarczy funkcja
- Logowanie przez `logging` do `logs/` (nie print)
- Sekrety tylko przez `.env` i `os.getenv()`, nigdy hardcoded
- Testy w `tests/` dla kazdego agenta i kroku pipeline

### CLI (`cli.py`)

- Komendy: `health`, `new-product <name>`, `status [slug]`, `list`
- Wyjscie przez `rich.console.Console` — tabele, kolory, czytelnosc
- Przy bledzie: wypisz komunikat i `sys.exit(1)`

### Agenci (`src/agents/`)

- Kazdy agent to plik `<nazwa>_agent.py` z funkcja `run(product: dict) -> dict`
- Agent zwraca zaktualizowany slownik produktu z nowymi polami
- Uzyj `anthropic.Anthropic()` z kluczem z `os.getenv("ANTHROPIC_API_KEY")`
- Domyslny model: `claude-sonnet-4-6` (aktualizuj jesli pojawi sie nowszy)

### Pipeline (`src/pipeline/`)

- Kazdy krok to plik `<numer>_<nazwa>.py` z funkcja `run(product: dict) -> dict`
- Kroki wywolywane sekwencyjnie, stan zapisywany do `data/products/<slug>.json`
- Krok moze byc pominiely jesli pole juz istnieje w JSON (idempotentnosc)

### Dane produktu (`data/products/<slug>.json`)

Struktura pliku produktu:
```json
{
  "slug": "vase-modern-01",
  "name": "Modern Vase 01",
  "category": "decor",
  "description": "",
  "status": "draft",
  "steps_completed": [],
  "etsy_title": "",
  "etsy_description": "",
  "etsy_tags": [],
  "etsy_price": null,
  "etsy_listing_id": null
}
```

### Git

- Commituj po kazdym wiekszym kroku (nowy agent, nowy krok pipeline, nowa komenda)
- Komunikaty commitow po angielsku, format: `type: opis` (feat, fix, refactor, docs)
- Nie commituj `.env`, `logs/`, `__pycache__/`

## Komendy CLI

```bash
python cli.py health                        # sprawdz konfiguracje
python cli.py new-product "Modern Vase"     # nowy produkt
python cli.py new-product "Ring" -c jewelry # z kategoria
python cli.py status                        # wszystkie produkty
python cli.py status modern-vase            # konkretny produkt
python cli.py list                          # tabela produktow
python cli.py list --status-filter draft    # filtruj
```

## Zmienne srodowiskowe

Skopiuj `.env.example` do `.env` i uzupelnij klucze:

```
ANTHROPIC_API_KEY=   # wymagane
OPENAI_API_KEY=      # opcjonalne (obrazy)
ETSY_API_KEY=        # wymagane do publikacji
ETSY_API_SECRET=     # wymagane do publikacji
ETSY_SHOP_ID=        # wymagane do publikacji
```
