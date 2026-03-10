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

### Faza 4 — Skalowalność
- [ ] SQLite + SQLModel zamiast flat JSON (> 50 produktów)
- [ ] `cli.py stats` — przychody, popularność tematów, konwersje
- [ ] Etsy Analytics API integration (views, favorites)
- [ ] Batch processing: `new-product --batch 5`

### Faza 5 — Automatyzacja
- [ ] Cron job: daily trend scan → auto draft
- [ ] Webhook Etsy → update meta po sprzedaży
- [ ] Restock alert: auto-reprint gdy zapas < 3

---

## Modele AI

| Agent         | Model              | Uzasadnienie                         |
|---------------|--------------------|--------------------------------------|
| listing_agent | claude-sonnet-4-6  | Najlepszy stosunek jakości do kosztu |
| design_agent  | claude-sonnet-4-6  | SVG path generation                  |
| trend_agent   | claude-haiku-4-5   | Prosta klasyfikacja, koszt ważny     |
| (future) seo  | claude-sonnet-4-6  | A/B testy tytułów                    |

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

*Ostatnia aktualizacja: 2026-03-10 przez Claude (architect v2)*
