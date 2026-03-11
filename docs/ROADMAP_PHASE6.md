# Roadmap Faza 6 — Plan sprintów
> Plan implementacji produkcyjnej jakości SVG + STL.
> Aktualizuj po każdym ukończonym zadaniu.
> Powiązana specyfikacja: `docs/svg_stl_pipeline.md`

**Status:** 🔴 W TOKU (od 2026-03-11)
**Szacowany czas:** 3 sprinty × ~3h = ~9h pracy

---

## Sprint 1 — Naprawa model_agent.py
**Cel:** Poprawne STL dla kształtów wklęsłych (gwiazda, ludzik, płatek śniegu)
**Pliki:** `src/agents/model_agent.py`, `requirements.txt`
**Status:** ⬜ TODO

### Zadania

- [ ] **S1.1** `requirements.txt` — dodaj `shapely>=2.0.0`
  - Weryfikacja: `python -c "from shapely.geometry import Polygon; print('OK')"`

- [ ] **S1.2** Bezier sampling: 8 → 32 punkty
  - Plik: `model_agent.py`
  - Zmiana: `for k in range(1, 9)` → `for k in range(1, 33)` (2 miejsca: C i Q)
  - Dodaj stałą: `BEZIER_SAMPLES = 32`
  - Test: wygeneruj STL z kształtu serca i sprawdź gładkość krawędzi

- [ ] **S1.3** Shapely polygon offset — zastąp `_offset_contour()`
  - Plik: `model_agent.py`, klasa `PurePythonSTLWriter`
  - Stara metoda: `_offset_contour()` (centroid scaling) → USUŃ lub zachowaj jako fallback
  - Nowa: `offset_contour_shapely(points, offset_mm)` używa `Polygon.buffer()`
  - Fallback gdy shapely niedostępne: stara metoda + warning log
  - Test: offset konturu gwiazdy → sprawdź czy promienie są równe

- [ ] **S1.4** Ear-clipping triangulation — zastąp `_triangulate_flat()`
  - Plik: `model_agent.py`, klasa `PurePythonSTLWriter`
  - Stara metoda: fan triangulation od vertex[0] → działa TYLKO dla convex
  - Nowa: `earclip_triangulate(contour)` — własna implementacja ear-clipping O(n²)
  - Test kształtów: gwiazda, ludzik piernikowy, płatek śniegu → sprawdź że STL valid

- [ ] **S1.5** Taper geometry — krawędź tnąca
  - Plik: `model_agent.py`, klasa `PurePythonSTLWriter`
  - Nowa metoda: `extrude_tapered_cutter(contour, config)`
  - Profil: dół cutting_edge=0.4mm → taper_height=3mm → wall_thick=1.2mm → góra
  - Parametry z `product_types.yaml`: `blade_thickness`, `taper_height`
  - Test: zmierzyć STL w slicerze → dolna krawędź 0.4mm, górna 1.2mm

- [ ] **S1.6** Fillet górnej krawędzi
  - Plik: `model_agent.py`
  - Implementacja: bevel ring z interpolacją arc 0.8-1.2mm na górnej krawędzi
  - Parametr: `fillet_top` z product_types.yaml

- [ ] **S1.7** Zaktualizuj testy
  - Plik: `tests/test_model_agent.py`
  - Dodaj testy dla: ear-clipping z concave polygon, shapely offset, taper profile

**Weryfikacja Sprintu 1:**
```bash
python -m pytest tests/test_model_agent.py -v
python cli.py new-product "test star" -t cutter -s M
# Sprawdź: data/products/cutter/test-star/models/M_cutter.stl w PrusaSlicer
```

---

## Sprint 2 — Compound SVG + Printability Validator
**Cel:** SVG z dwoma warstwami (outer + stamp), cute styl, walidacja drukowalności
**Pliki:** `src/agents/design_agent.py`, nowy `src/utils/printability_validator.py`
**Status:** ✅ UKOŃCZONY (2026-03-11)

### Zadania

- [x] **S2.1** Nowy moduł: `src/utils/printability_validator.py`
  - Funkcja: `validate_svg(svg_path, size_mm) -> ValidationResult`
  - Sprawdzenia (patrz svg_stl_pipeline.md §5.1):
    - Zamknięte ścieżki (path ends Z)
    - Min szerokość elementu ≥ 5mm (sampling contour, min distance check)
    - Min kąt wklęsły ≥ 25° (cross product check)
    - Circle fit (bounding box ≤ size_mm)
    - Odizolowane detale
  - Testy: `tests/test_printability_validator.py`

- [x] **S2.2** Nowy format SVG — compound paths (`_write_svg()` → raw XML, `<g id="outer">` + `<g id="stamp">`)
- [x] **S2.3** Nowy Claude prompt — outer contour (cute kawaii cartoon, chubby, Etsy style)
- [x] **S2.4** Stamp details proceduralne (mock) — `_stamp_elements_mock()` (oczy+smile dla creature, dots dla roślin)
- [x] **S2.5** 31 kształtów: +16 nowych (cat, dog, rabbit, hen, bear, owl, llama, fish, bird, apple, cactus, strawberry, tulip, easter_egg, crown, cookie)
- [x] **S2.6** XXXL=150mm w SIZE_MM; 257 testów passing

**Weryfikacja Sprintu 2:**
```bash
python -m pytest tests/test_design_agent.py tests/test_printability_validator.py -v
python cli.py new-product "cute cat" -t cutter
# Sprawdź: data/products/cutter/cute-cat/source/*.svg — otwórz w Inkscape
```

---

## Sprint 3 — Stamp STL + Pipeline Integration
**Cel:** Generowanie dwóch STL na rozmiar, nowe nazewnictwo, pełna integracja
**Pliki:** `src/agents/model_agent.py`, `src/pipeline/orchestrator.py`, `src/utils/product_io.py`
**Status:** ⬜ TODO (po Sprint 2)

### Zadania

- [ ] **S3.1** model_agent — generowanie stamp.stl
  - Plik: `model_agent.py`, nowa metoda `generate_stamp_stl()`
  - Parsuj `<g id="stamp">` z compound SVG
  - Generuj: base plate (3mm solid extrude) + raised features (2.0mm extrude)
  - Clearance: stamp outline = outer inset 0.4mm (3D clearance)
  - Parametry z config: `stamp.base_height`, `stamp.relief_height`

- [ ] **S3.2** model_agent — nowe nazewnictwo plików
  - Stare: `{slug}_M_cutter.stl`
  - Nowe: `M_cutter.stl`, `M_stamp.stl`
  - Update `generate()` i `generate_all()`

- [ ] **S3.3** model_agent — generowanie dla wszystkich 6 rozmiarów
  - `generate_all()`: iteruj po wszystkich SVG w source/ (XS.svg → XXXL.svg)
  - Dla każdego rozmiaru: generuj _cutter.stl + _stamp.stl
  - Wynik: 12 plików w models/

- [ ] **S3.4** orchestrator.py — integracja nowego pipeline
  - Update `run_pipeline()`: wywołuje design_agent → printability_validator → model_agent
  - Zapisuj do meta.json: `steps_completed`, `stl_count` (powinno być 12)
  - Status po ukończeniu: `ready_for_render`

- [ ] **S3.5** product_io.py — wsparcie dla nowego nazewnictwa
  - Update `find_stl_files()` (jeśli istnieje) dla nowego wzorca `{SIZE}_{TYPE}.stl`
  - Dodaj helper: `list_stl_files(slug) -> dict[str, Path]`

- [ ] **S3.6** config — aktualizacja product_types.yaml
  - Dodaj brakujące parametry: `blade_thickness`, `taper_height`, `fillet_top`, `clearance_3d`
  - Sprawdź zgodność z wytycznymi z `docs/svg_stl_pipeline.md §4.3`

- [ ] **S3.7** Testy integracyjne
  - `tests/test_model_agent.py` — test stamp STL generation
  - `tests/test_orchestrator.py` — test pełnego pipeline 6 rozmiarów
  - Mock SVG z compound paths (fixtures/)

**Weryfikacja Sprintu 3:**
```bash
python -m pytest tests/ -v
python cli.py new-product "gingerbread man" -t cutter
# Sprawdź: 12 plików STL w data/products/cutter/gingerbread-man/models/
# Wgraj M_cutter.stl i M_stamp.stl do PrusaSlicer → wydrukuj testowo
```

---

## Definicja "ukończone" (Definition of Done)

Sprint jest ukończony gdy:
1. Wszystkie testy (`pytest tests/`) przechodzą
2. `python cli.py new-product "test topic" -t cutter` generuje 12 STL
3. Pliki STL wczytują się poprawnie w PrusaSlicer / Creality Print bez błędów
4. trimesh walidacja: watertight=True, volume>0 dla wszystkich 12 plików
5. Commit na gita z tagiem `phase6-sprint{N}-complete`

---

## Notatki z sesji

### 2026-03-11
- Analiza kodu: zidentyfikowane 4 krytyczne problemy (triangulacja, offset, bezier, brak taper)
- Analiza dokumentów właściciela: wizja cute cartoon SVG + compound paths + 6 rozmiarów
- Decyzja architektoniczna: 1 compound SVG → 2 STL per rozmiar = 12 plików produkcyjnych
- Shapely wybrana jako biblioteka do polygon offset (stabilna, production-ready)
- Pliki docs/ zaktualizowane, Plan gotowy do implementacji

---

*Ostatnia aktualizacja: 2026-03-11*
