# etsy3d — Architektura systemu

> Dokument przejęty i utrzymywany przez Claude (architektura v2).
> Aktualizuj po każdej znaczącej zmianie strukturalnej.

---

## Wizja

Automatyczny, w pełni idempotentny pipeline do generowania i publikowania
produktów drukowanych w 3D na Etsy. Każdy produkt powstaje w 6 etapach:

```
[Trend] → [Listing] → [SVG] → [STL] → [Renders] → [Etsy Publish]
```

Każdy etap jest niezależnym agentem. Pipeline można wznawiać od dowolnego
kroku. Stan produktu żyje w `data/products/{slug}/`.

---

## Struktura katalogów (v2)

```
etsy3d/
├── cli.py                        # Punkt wejścia CLI (click)
├── ARCHITECTURE.md               # Ten plik
├── requirements.txt              # Zależności
│
├── config/                       # YAML — jedyne źródło konfiguracji
│   ├── pricing.yaml              # Zakresy cen, mnożniki rozmiarów
│   ├── product_types.yaml        # Parametry cutter/stamp/set (wymiary, ścianki)
│   ├── etsy.yaml                 # Taxonomy IDs, limity API, kolejność zdjęć
│   └── prompts.yaml              # Szablony promptów dla agentów (base templates)
│
├── src/
│   ├── agents/                   # Agenci — jeden plik = jeden etap
│   │   ├── trend_agent.py        # Analiza trendów (pytrends + baza statyczna)
│   │   ├── listing_agent.py      # Generuje listing SEO (Claude API)
│   │   ├── design_agent.py       # Generuje SVG kształtu (DALL-E / Claude / mock)
│   │   ├── model_agent.py        # SVG → STL (OpenSCAD / pure_python)
│   │   ├── render_agent.py       # STL → JPG 2000×2000 (Pillow)
│   │   └── etsy_agent.py         # Publikacja na Etsy (OAuth2, API v3)
│   │
│   ├── pipeline/
│   │   └── orchestrator.py       # Łączy agentów, zarządza stanem
│   │
│   └── utils/
│       ├── product_io.py         # load/save/update meta.json + listing.json
│       ├── claude_client.py      # Centralny klient Claude z retry + logging
│       ├── etsy_client.py        # Wrapper Etsy API v3 z retry + rate-limit
│       └── config_loader.py      # Ładowanie YAML z config/
│
├── data/
│   ├── products/                 # Dane produktów
│   │   └── {slug}/
│   │       ├── meta.json         # Status, created_at, etapy, listing_id
│   │       ├── listing.json      # title, description, tags, price
│   │       ├── design.json       # metadane SVG
│   │       ├── source/           # *.svg + opcjonalne *_dalle_raw.png
│   │       ├── models/           # *.stl (S/M/L)
│   │       ├── renders/          # hero/lifestyle/sizes/detail/info.jpg
│   │       └── listing_export.json  # dry-run export
│   └── templates/                # Szablony promptów (opcjonalne override)
│
├── tests/
│   ├── fixtures/                 # Przykładowe SVG, JSON, STL do testów
│   ├── test_listing_agent.py
│   ├── test_design_agent.py
│   ├── test_model_agent.py
│   ├── test_trend_agent.py
│   └── test_orchestrator.py
│
└── logs/                         # Logi agentów (gitignored)
```

---

## Schemat stanu produktu

```
          new-product
              │
           [draft]
              │
      listing generated
              │
        [listing_ready]
              │
       SVG generated
              │
        [design_ready]
              │
       STL generated
              │
        [model_ready]
              │
      Renders generated
              │
     [ready_for_publish]
              │
   publish / etsy-auth
              │
           [listed]
              │
         (Etsy Live)
```

Błędy: `design_error`, `model_error`, `render_error` — pipeline zatrzymuje się,
log wskazuje krok do naprawy.

---

## Zasady architektury

### 1. Konfiguracja przez YAML, nie przez hardcode
Ceny, wymiary, taxonomy IDs, mnożniki rozmiarów — wyłącznie w `config/*.yaml`.
Agenci importują przez `utils/config_loader.py`.

### 2. Centralny klient Claude
Wszyscy agenci używają `utils/claude_client.py` — jedno miejsce dla retry,
logowania tokenów, rate-limit.

### 3. Centralny I/O produktu
Wszystkie operacje na `meta.json` i `listing.json` przez `utils/product_io.py`.
Brak rozrzuconego `json.loads()` / `json.dumps()` po agentach.

### 4. Idempotentność
Każdy krok sprawdza `meta["steps_completed"]`. Jeśli krok ukończony i pliki
istnieją — pomija. Re-run bezpieczny.

### 5. Walidacja na wyjściu agenta
Każdy agent zwraca `{"success": bool, "error": str | None, ...}`.
Orchestrator decyduje czy kontynuować czy zatrzymać.

### 6. Testy przez mocki
Testy agentów nie dotykają prawdziwych API. `conftest.py` dostarcza fixtures.

---

## Priorytety rozwoju (Roadmap)

### Faza 1 — Fundament ✅ UKOŃCZONA (2026-03-10)
- [x] Architektura v1 (pipeline end-to-end)
- [x] `config/*.yaml` — pricing, product_types, etsy, trends
- [x] `src/utils/product_io.py` — centralny I/O
- [x] `src/utils/claude_client.py` — centralny klient Claude z retry
- [x] `src/utils/config_loader.py` — cachowane ładowanie YAML
- [x] listing_agent, trend_agent, etsy_agent, orchestrator, render_agent — używają utils

### Faza 2 — Jakość danych ✅ UKOŃCZONA (2026-03-10)
- [x] model_agent: wymiary z product_types.yaml
- [x] STL walidacja: trimesh (watertight, volume, normals — graceful fallback)
- [x] Testy: 55 passing (conftest, fixtures, mock_anthropic, wszystkie agenty)

### Faza 3 — Jakość wizualna ✅ UKOŃCZONA (2026-03-10)
- [x] blender_render_agent.py: Blender 4.0.2 headless, EEVEE renderer
- [x] 3-point lighting, PLA material, 5 trybów (hero/lifestyle/detail/sizes/info)
- [x] Pillow post-processing: badge overlay, tekst, info panel
- [x] Auto-fallback na Pillow gdy brak Blendera
- [x] orchestrator używa BlenderRenderAgent jako domyślny

### Faza 4 — Skalowalność ✅ UKOŃCZONA (2026-03-10)
- [x] SQLite + SQLModel zamiast flat JSON (> 50 produktów)
- [x] `cli.py stats` — przychody, popularność tematów, konwersje
- [x] Etsy Analytics API integration (views, favorites) — analytics-sync + ListingStats
- [x] Batch processing: `new-product --batch N`

### Faza 5 — Automatyzacja ✅ UKOŃCZONA (2026-03-10)
- [x] Cron job: daily trend scan → auto draft (`trend-scan`)
- [x] Webhook Etsy → update meta po sprzedaży (`webhook-serve`, RECEIPT_PAID)
- [x] Restock alert: alerty + optional auto_reprint (`restock-check`)

### Faza 8 — SVG Quality Sprint (DALL-E+potrace pipeline) ✅ PARAMETRY FINALNE (2026-03-12)

#### Stan na 2026-03-12
- [x] `_make_svg_dalle_potrace()` — nowy tryb `mode='dalle'` w DesignAgent
- [x] Pipeline: DALL-E 3 PNG → ImageMagick threshold → potrace → SVG
- [x] `DALLE_PROMPTS` — 14 tematów z dedykowanymi promptami (anty-3D, coloring book style)
- [x] `SHAPE_HINTS` — wskazówki wizualne dla Claude API (tryb real)
- [x] `_validate_path` — obsługa multi-subpath (M/Z balance zamiast single-path)
- [x] `max_tokens` 1024→2048 (fix truncation dla złożonych kształtów Claude)
- [x] potrace skalowanie: viewBox × 10 (fix: było /10, powodowało out-of-bounds)
- [x] transform `translate(0,size_mm) scale(1,-1)` — y-flip bez podwójnego skalowania
- [x] walidacja potrace z marginesem 3× (viewBox tnie resztę)
- [x] `stroke-width=1.5mm`, `fill="white"`, `fill-rule="evenodd"`
- [x] PNG zapisywany jako `{size}_dalle_raw.png` obok SVG (persystencja)
- [x] **v9 — parametry finalne:** silhouette prompts (rubber stamp style), threshold=50%, turdsize=80, opttolerance=0.5 — zero morphology
- [x] **v11 — design_agent fixes:**
  - DALL-E prompt: explicit NO circle/oval/border/frame
  - subpath filter: keep all segments >= 10% of longest (nie tylko najdłuższy)
  - fix canvas frame: `M0` prefix segment usuwany przed liczeniem progu 10%
  - wynik: 3 subpaths, 52 nodes, 5KB — czysty wieniec bez tła ✅
- [x] **model_agent OpenSCAD rewrite** (`OpenSCADGenerator._scad_cutter/_scad_stamp`):
  - `_scad_stamp`: kwadratowa baza size_mm×size_mm×4mm + `linear_extrude(import(svg))` relief 1.5mm
  - `_scad_cutter` TYP A (n_subpaths ≤ 3): `offset(r=4.8) import(svg)` minus `offset(r=3.0)` — organiczny kształt
  - `_scad_cutter` TYP B (n_subpaths > 3): zaokrąglony prostokąt bbox+12mm jako kontener ściany
  - `generate_scad(svg_path=)` + `_generate_via_openscad(svg_path=)` — przekazanie ścieżki SVG
  - test: XS_cutter.stl (52KB watertight) + XS_stamp.stl (469KB watertight) ✅
- [ ] Regeneracja 22 produktów (XS) z DALL-E+potrace
- [ ] Rebuild STL po nowych SVG

#### Parametry pipeline v9 (finalne)
| krok | parametr | wartość |
|------|----------|---------|
| DALL-E prompt | styl | silhouette / rubber stamp, solid black fill |
| ImageMagick | threshold | 50%, zero blur, zero morphology |
| potrace | turdsize | 80 |
| potrace | alphamax | 1.5 |
| potrace | opttolerance | 0.5 |
| wynik | nodes | ~142, 1 path, ~6KB |

#### Tryby design_agent.py (aktualne)
| mode | backend | opis |
|------|---------|------|
| `mock` | procedural | 31 kształtów, bez API, CI/testy |
| `real` | Claude API | claude-opus-4-6, multi-subpath SVG |
| `auto` | Claude→mock | real jeśli ANTHROPIC_API_KEY dostępny |
| `dalle` | DALL-E+potrace | DALL-E 3 PNG → ImageMagick → potrace → SVG |

### Faza 9 — Typ B Pipeline: Standard Base + AI Stamp 🔴 PLANOWANA (od 2026-03-15)

> Decyzja architektoniczna: porzucamy DALL-E+potrace (Faza 8) na rzecz czystej
> geometrii Python (Shapely) jako źródła prawdy. SVG = artefakt podglądu.
> STL generowany z OpenSCAD polygon() — nie z import(svg).

#### Kontekst biznesowy
- Skala: 2-5k produktów
- Typ B = 80%+ oferty: standardowy cutter (baza) + unikalny wzór stempla
- Strategia topowych sprzedawców Etsy: N wzorów × M baz × 6 rozmiarów = N×M×6 listingów

#### Pipeline Typ B

```
[topic] ──→ Claude JSON plan ──→ Shapely relief polygon
                │
[base_shape] ──→ Shapely base polygon ──→ OpenSCAD polygon() ──→ cutter STL
                                       ──→ OpenSCAD polygon() ──→ stamp STL
                                       ──→ SVG (preview/Etsy)
```

#### Krok A — Zależności i środowisko

- [ ] `pip install shapely` (jest w requirements.txt, brak w venv)
- [ ] Weryfikacja: `python -c "import shapely; print(shapely.__version__)"`
- [ ] Weryfikacja OpenSCAD: `openscad --version` (✅ 2021.01)
- [ ] Usunąć `openai` z requirements.txt (DALL-E nie będzie używany)

#### Krok B — config/base_shapes.yaml

20 standardowych baz (3 fale wdrożenia) z metadanymi:
- Tier 1/Core (8): heart, circle, rectangle, squircle, star5, arch, oval, cloud
- Tier 2/Variant (6): scalloped_circle, wavy_square, hexagon, octagon, heart_wide, ghost
- Tier 3/Seasonal (6): christmas_tree, snowflake, pumpkin, bunny, easter_egg, bell

Pola per shape: `label`, `tier`, `seasonal`, `peak_months`, `canvas_ratio`,
`openscad_module`, `etsy_search_volume`, `aspect_ratio` (opt), `corner_radius_ratio` (opt)

#### Krok C — src/shapes/ (nowy moduł)

```
src/shapes/
  __init__.py          ← eksport publicznego API
  base_shapes.py       ← 20 funkcji → Shapely Polygon; get_base(name, size_mm)
  svg_export.py        ← Shapely Polygon → SVG (preview, nie do OpenSCAD)
  scad_export.py       ← Shapely Polygon → OpenSCAD polygon() → STL via CLI
  stamp_elements.py    ← Claude JSON → Shapely MultiPolygon (relief)
```

**base_shapes.py** — publiczne API:
```python
get_base(name: str, size_mm: float) -> shapely.Polygon
list_bases(tier: int | None = None) -> list[str]
```

**scad_export.py** — publiczne API:
```python
cutter_stl(base: Polygon, size_mm: float, cfg: dict, out: Path) -> Path
stamp_stl(base: Polygon, relief: MultiPolygon, size_mm: float, cfg: dict, out: Path) -> Path
```

**svg_export.py** — publiczne API:
```python
base_to_svg(base: Polygon, size_mm: float, out: Path, title: str = "") -> Path
```

**stamp_elements.py** — publiczne API:
```python
plan_stamp(topic: str, base: Polygon, client) -> dict  # Claude → JSON
build_relief(plan: dict, base: Polygon) -> MultiPolygon
```

#### Krok D — Refactor design_agent.py

**Usunąć:**
- tryb `dalle` + cała funkcja `_make_svg_dalle_potrace()` (~300 linii)
- tryb `real` + `_make_svg_real()` (Claude generujący SVG path d=)
- `DALLE_PROMPTS`, `SHAPE_HINTS` słowniki
- `_validate_path()` (nie potrzebna)
- `_stamp_elements_mock()` → przeniesiona do `src/shapes/stamp_elements.py`
- `_path_*` funkcje (31 kształtów) → zastąpione przez `src/shapes/base_shapes.py`

**Zachować/przepisać:**
- `DesignAgent` klasa z nowym API
- `generate(topic, product_type, sizes, output_dir)` — ta sama sygnatura
- tryb `mock` → używa `base_shapes.get_base()` + `svg_export.base_to_svg()`
- tryb `real` (Typ B) → Claude planuje JSON stamp, Python buduje geometrię

**Nowe tryby design_agent:**
| mode | opis |
|------|------|
| `mock` | Shapely base + pusty relief (testy/CI) |
| `typeB` | Shapely base + Claude JSON stamp (produkcja) |
| `auto` | `typeB` jeśli ANTHROPIC_API_KEY, inaczej `mock` |

#### Krok E — Refactor model_agent.py

**Usunąć:**
- `SVGPathParser` klasa — nie parsujemy już SVG do STL
- `OpenSCADGenerator._scad_cutter` z `import(svg)` — zastąpiony przez `scad_export.py`
- `OpenSCADGenerator._scad_stamp` z `import(svg)` — j.w.
- `PurePythonSTLWriter` — zastąpiony przez OpenSCAD via `scad_export.py`
- `_generate_via_openscad()` z svg_path param

**Zachować:**
- `STLValidator` — walidacja trimesh (watertight, volume)
- `ModelAgent` klasa z tym samym publicznym API
- `generate_all(slug, product_type, sizes, source_dir, output_dir)` — ta sama sygnatura

**Przepisać:**
```python
# Nowy przepływ w ModelAgent.generate_all():
base = base_shapes.get_base(meta["base_shape"], size_mm)
cutter_path = scad_export.cutter_stl(base, size_mm, cfg, out_dir/f"{size}_cutter.stl")
stamp_path  = scad_export.stamp_stl(base, relief, size_mm, cfg, out_dir/f"{size}_stamp.stl")
```

#### Krok F — Schema meta.json (nowe pola)

```json
{
  "product_subtype": "B",
  "base_shape": "heart",
  "stamp_topic": "floral wreath",
  "stamp_plan": { ... }
}
```

Aktualizacja `src/utils/product_io.py` — brak zmian API (backward compatible).

#### Krok G — Update orchestrator.py

- Nowy krok pipeline: `design_step` wywołuje `design_agent.generate()` z `base_shape`
- `base_shape` odczytywane z `meta["base_shape"]` (ustawiane przy `new-product`)
- Jeśli brak `base_shape` → domyślnie `heart`
- `model_step` używa nowego `ModelAgent` bez SVG path

#### Krok H — Update CLI (cli.py)

Nowe opcje `new-product`:
```bash
python cli.py new-product "Floral Wreath" --subtype B --base heart
python cli.py new-product "Floral Wreath" --subtype B --base circle
python cli.py new-product --topics "cat,dog,bear" --subtype B --base heart
```

Update `list`:
- Dodać kolumnę `Base` w tabeli produktów
- `status` wyświetla `base_shape` + `stamp_topic`

#### Krok I — Testy

```
tests/
  test_base_shapes.py      ← get_base() dla 8 Fala 1 shapes; rozmiary XS-XXXL
  test_svg_export.py       ← SVG walidacja (closed paths, viewBox, wymiary)
  test_scad_export.py      ← .scad syntax; OpenSCAD CLI generuje STL; trimesh OK
  test_stamp_elements.py   ← mock plan → MultiPolygon; Claude mock → JSON parseable
  test_design_agent.py     ← update (usunąć dalle/real testy, dodać typeB/mock)
  test_model_agent.py      ← update (usunąć SVGPathParser testy)
```

#### Krok J — Fala 2 shapes (6 dodatkowych)

Po ustabilizowaniu Fali 1:
`scalloped_circle`, `wavy_square`, `hexagon`, `octagon`, `heart_wide`, `ghost`

Każdy: funkcja w `base_shapes.py` + metadane w `base_shapes.yaml` + testy.

#### Krok K — Fala 3 seasonal (6 shapes)

Przed sezonem (Q3 2026):
`christmas_tree`, `snowflake`, `pumpkin`, `bunny`, `easter_egg`, `bell`

#### Krok L — Pierwsze produkty Typ B (10 produktów)

```bash
python cli.py new-product "Floral Wreath" --subtype B --base heart
python cli.py new-product "Floral Wreath" --subtype B --base circle
# ...itd. — ten sam wzór, różne bazy = 3-5 listingów per wzór
```

#### Krok M — Typ A pipeline (future)

Unikalne siluwety (kot, pies, królik itd.):
- `base_shapes.py` obsługuje Typ A przez `get_typeA_silhouette(topic, size_mm)`
- Claude JSON → bardziej złożone komponenty (głowa + uszy + itd.)
- Osobne zadanie po ustabilizowaniu Typ B

#### Kolejność implementacji (sprinty)

| Sprint | Kroki | Czas | Efekt |
|--------|-------|------|-------|
| 9.1 | A + B | sesja 1 | Shapely + config gotowy |
| 9.2 | C (base_shapes + svg_export) | sesja 2 | 8 kształtów generuje SVG |
| 9.3 | C (scad_export + stamp_elements) | sesja 3 | OpenSCAD STL bez SVG pośredniego |
| 9.4 | D + E (refactor agentów) | sesja 4 | Stary kod zastąpiony |
| 9.5 | F + G + H (meta, orchestrator, CLI) | sesja 5 | End-to-end pipeline Typ B |
| 9.6 | I (testy) | sesja 6 | CI green |
| 9.7 | J + K (Fala 2 + 3) | sesja 7-8 | 20 baz gotowych |
| 9.8 | L (pierwsze produkty) | sesja 9 | 10 listingów gotowych do Etsy |

---

### Faza 6 — Produkcyjna jakość SVG + STL 🟡 W TOKU (od 2026-03-11)
> Pełna specyfikacja: `docs/svg_stl_pipeline.md`
> Plan sprintów: `docs/ROADMAP_PHASE6.md`

#### Sprint 1 — Naprawa STL (model_agent.py) ✅ (2026-03-11)
- [x] Bezier sampling: 8 → 32 punkty na krzywą
- [x] Shapely polygon offset (zastąpienie centroid scaling)
- [x] Ear-clipping triangulation (zastąpienie fan triangulation)
- [x] Taper geometry — krawędź tnąca zbieżna 8-12° (cutting edge 0.4mm)
- [x] Fillet config (taper_height: 3.0, fillet_top: 1.0 w product_types.yaml)
- [x] `shapely` dodany do requirements.txt

#### Sprint 2 — Compound SVG (design_agent.py) ✅ (2026-03-11)
- [x] Nowy format SVG: `<g id="outer">` + `<g id="stamp">` (raw XML)
- [x] Nowy Claude prompt — styl "cute kawaii cartoon, chubby proportions"
- [x] `src/utils/printability_validator.py` — validate_svg() → ValidationResult
- [x] Biblioteka mock: 31 kształtów (+16 nowych: cat, dog, rabbit, hen, bear, owl, llama, fish, bird, apple, cactus, strawberry, tulip, easter_egg, crown, cookie)
- [x] 6 rozmiarów: XS=50mm, S=60mm, M=75mm, L=90mm, XL=110mm, XXXL=150mm
- [x] _stamp_elements_mock(): stamp_outline + creature faces + plant dots

#### Sprint 3 — Stamp/Embosser STL + Pipeline ✅ (2026-03-11)
- [x] model_agent: generowanie 2 STL na rozmiar ({SIZE}_cutter.stl + {SIZE}_stamp.stl)
- [x] Stamp geometry: base 3mm + raised relief 2mm (config: base_height=3.0, relief_height=2.0)
- [x] clearance_3d=0.2mm w config/product_types.yaml
- [x] generate_all() → cutter+stamp per size, szuka S.svg/M.svg/L.svg, zwraca stl_files[]
- [x] orchestrator: validate_svg() przed STL, nowe API generate_all()
- [x] product_io: list_stl_files(slug, product_type)

#### Nowa struktura plików produktu po Fazie 6
```
data/products/{type}/{slug}/
├── source/
│   ├── S.svg, M.svg, L.svg, XL.svg, XXL.svg, XXXL.svg  ← compound SVG
├── models/
│   ├── S_cutter.stl,  S_stamp.stl
│   ├── M_cutter.stl,  M_stamp.stl
│   └── ...  (12 plików STL łącznie)
```

### Faza 7 — Render Quality + Batch Production + Publish Pipeline ✅ (2026-03-11)

#### Sprint 7.1 — Render Quality dla dual-type STL ✅
- [x] blender_render_agent: `_find_stl_files()` — nowe nazewnictwo `{SIZE}_{type}.stl` + legacy fallback
- [x] blender_render_agent: stamp-specific overlays (hero badge "Clay Embosser", detail "3mm base + 2mm relief")
- [x] blender_render_agent: `product_type` przekazywany do `_render_sizes`, `_overlay_hero`, `_overlay_detail`
- [x] render_agent: `_render_detail` i `_render_sizes` używają `product_type` zamiast hardcoded "cutter"
- [x] render_agent: `_load_product_image` wykrywa `{SIZE}.svg` → informacyjny placeholder (blue tint)
- [x] 261 testów passing (+2)

#### Sprint 7.2 — Batch nowych produktów ✅
- [x] orchestrator: wszystkie rozmiary z configa (XS,S,M,L,XL,XXXL) zamiast hardcoded ["S","M","L"]
- [x] orchestrator: `product_type` w size_map zamiast hardcoded "cutter"
- [x] CLI: `--topics 'cat,dog,bear'` — named batch generation
- [x] 10 nowych produktów wygenerowanych: cute-cat, cute-dog, teddy-bear, wise-owl, llama-alpaca,
      tropical-fish, little-bird, red-apple, cute-cactus, strawberry (każdy: 6 SVG + 12 STL + 5 renders)

#### Sprint 7.3 — Publish Pipeline ✅
- [x] CLI `publish` / `open-product`: używają `find_product_dir()` zamiast flat `DATA_DIR/slug`
- [x] CLI `publish` / `open-product`: opcja `--type` dla bezpośredniego lookup
- [x] CLI `publish-all`: masowa publikacja wszystkich `ready_for_publish` produktów
- [x] `etsy_agent.publish()`: parametr `force_dry_run` (generuje listing_export.json bez API)
- [x] 16 produktów ready_for_publish — dry-run listing_export.json wygenerowany dla wszystkich

---

## Modele AI

| Agent         | Model              | Uzasadnienie                         |
|---------------|--------------------|--------------------------------------|
| listing_agent | claude-opus-4-6    | Najlepszy stosunek jakości do kosztu |
| design_agent  | claude-opus-4-6    | SVG path generation                  |
| trend_agent   | claude-haiku-4-5   | Prosta klasyfikacja, koszt ważny     |
| (future) seo  | claude-opus-4-6    | A/B testy tytułów                    |

---

## Zmienne środowiskowe

| Zmienna              | Wymagana | Opis                              |
|----------------------|----------|-----------------------------------|
| ANTHROPIC_API_KEY    | Zawsze   | Claude API                        |
| OPENAI_API_KEY       | Opt.     | DALL-E 3 (design_agent mode=auto) |
| ETSY_API_KEY         | Publish  | Etsy app key                      |
| ETSY_API_SECRET      | Publish  | Etsy app secret                   |
| ETSY_SHOP_ID         | Publish  | ID sklepu Etsy                    |
| ETSY_ACCESS_TOKEN    | Publish  | OAuth2 (po etsy-auth)             |
| ETSY_REFRESH_TOKEN   | Publish  | OAuth2 refresh                    |

---

*Ostatnia aktualizacja: 2026-03-15 przez Claude (architect v2) — Faza 9: plan Typ B pipeline (Shapely geometry engine, 20 standard base shapes, bez DALL-E/potrace/import(svg))*
