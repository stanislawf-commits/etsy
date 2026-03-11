# SVG → STL Pipeline — Specyfikacja techniczna
> Dokument dla agentów AI i deweloperów. Opisuje cały proces produkcji plików 3D.
> Źródła: wstepne_załozenia_projektowe/ + decyzja architektoniczna 2026-03-11.
> **Ten plik jest source of truth dla design_agent.py i model_agent.py.**

---

## 1. Cel i kontekst

Pipeline produkuje pliki 3D do druku (FDM/MSLA) dla sklepu Etsy — foremki do ciast
(cookie cutters) i stemple (embossery). Każdy produkt = 1 temat (np. "gingerbread man")
→ 6 rozmiarów × 2 pliki STL = 12 plików produkcyjnych.

Sprzęt produkcyjny: Bambulab P1S (FDM), drukarka MSLA. Materiał: food-safe PLA/PETG.

---

## 2. Przepływ danych

```
Temat (topic)
    │
    ▼
design_agent.py
    │  generuje compound SVG (outer + stamp layers)
    │  6 plików: S.svg, M.svg, L.svg, XL.svg, XXL.svg, XXXL.svg
    ▼
printability_validator.py
    │  sprawdza kąty, minimalne grubości, circle fit
    │  odrzuca lub poprawia automatycznie
    ▼
model_agent.py
    │  parsuje SVG → kontury
    │  generuje 2 STL na rozmiar:
    │    {size}_cutter.stl  — hollow cutting shell
    │    {size}_stamp.stl   — embossed base plate
    ▼
STLValidator
    │  trimesh: watertight, volume > 0, manifold
    │  printability: min wall 1.2mm, no overhangs > 45°
    ▼
models/ folder
    12 plików STL gotowych do druku
```

---

## 3. Format SVG — compound paths

### 3.1 Struktura pliku SVG

Każdy plik SVG musi zawierać dokładnie dwie warstwy (grupy):

```xml
<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{size_mm}mm" height="{size_mm}mm"
     viewBox="0 0 {size_mm} {size_mm}">

  <!-- LAYER 1: outer — zewnętrzna sylwetka cuttera -->
  <!-- Jedna zamknięta ścieżka. Używana do generowania hollow cutter shell. -->
  <g id="outer">
    <path id="outer_contour"
          d="M ... Z"
          fill="none"
          stroke="#000000"
          stroke-width="1.2"/>
  </g>

  <!-- LAYER 2: stamp — wewnętrzne detale embossera -->
  <!-- Wiele zamkniętych ścieżek. Używane do generowania raised relief. -->
  <g id="stamp">
    <!-- Kontur stempla = outer pomniejszony o clearance 5mm -->
    <path id="stamp_outline" d="M ... Z" fill="none" stroke="#666666" stroke-width="0.8"/>
    <!-- Detale twarzy, guziiki, falbanki itp. -->
    <circle id="eye_l"   cx="..." cy="..." r="2.5" fill="#333333"/>
    <circle id="eye_r"   cx="..." cy="..." r="2.5" fill="#333333"/>
    <path   id="smile"   d="M ... Q ... Z" fill="none" stroke="#333333" stroke-width="1.0"/>
    <circle id="btn_1"   cx="..." cy="..." r="3.0" fill="#333333"/>
    <circle id="btn_2"   cx="..." cy="..." r="3.0" fill="#333333"/>
    <circle id="btn_3"   cx="..." cy="..." r="3.0" fill="#333333"/>
    <path   id="ruffle_arm_l"  d="M ... Z" fill="#333333"/>
    <path   id="ruffle_arm_r"  d="M ... Z" fill="#333333"/>
    <path   id="ruffle_leg_l"  d="M ... Z" fill="#333333"/>
    <path   id="ruffle_leg_r"  d="M ... Z" fill="#333333"/>
  </g>

</svg>
```

### 3.2 Reguły SVG (obowiązkowe)

| Reguła | Wartość | Źródło |
|--------|---------|--------|
| Tylko zamknięte ścieżki | path musi kończyć się Z | W3C + Creality 2025 |
| Minimalna szerokość elementu | **5 mm** przy skali 50mm (S) | Treatstock + testy FDM 2026 |
| Grubość stroke (outer) | **1.2 mm** (stała) | Creality 2025, dysza 0.4mm |
| Clearance outer→stamp | **5 mm** równomierny | wytyczne projektowe |
| Promień zaokrąglenia krawędzi | min **0.8 mm** zero ostrych wierzchołków | food-safe standard |
| Kąt wklęsły min | **25°** (mniejsze → auto-fix lub odrzuć) | druk FDM praktyka |
| Styl wizualny | czarny obrys, białe tło, zero fill/gradient | standard SVG trace |
| Uproszczenie ścieżki | max 3 fale w ogonie/grzywie, max 3 wąsy | wydajność importu |

### 3.3 Rozmiary (6 wariantów)

| Rozmiar | Wymiar zewnętrzny | Skalowanie |
|---------|-------------------|------------|
| XS      | 50 mm             | bazowy     |
| S       | 60 mm             | ×1.20      |
| M       | 75 mm             | ×1.50      |
| L       | 90 mm             | ×1.80      |
| XL      | 110 mm            | ×2.20      |
| XXXL    | 150 mm            | ×3.00      |

**Ważne:** Skalowanie TYLKO w płaszczyźnie XY. Grubości ścianek, wysokości, promienie zaokrągleń
pozostają STAŁE we wszystkich rozmiarach.

### 3.4 Styl graficzny (dla agenta generującego SVG)

Grafiki muszą przypominać popularne produkty na Etsy — charakter "cute kawaii":
- **Proporcje chubby** — grube, zaokrąglone kończyny, duża głowa relative do ciała
- **Cartoon silhouette** — uproszczona, rozpoznawalna sylwetka, nie fotorealistyczna
- **Detale czytelne przy małych rozmiarach** — oczy min 5mm średnicy, guziki min 6mm
- **Brak cienkich elementów** — wąsy, ogon, palce NIE cieńsze niż 5mm przy skali 50mm
- **Inspiracja:** owce, koty, misie, ludziki piernikowe, zajączki, grzyby, kwiaty — styl Etsy 2025/2026

---

## 4. Geometria STL — dwa pliki na rozmiar

### 4.1 Plik cutter: `{slug}_{size}_cutter.stl`

```
Widok przekroju (bok):

  ┌─────────────────────────────┐  ← górna krawędź (fillet 0.8-1.2mm)
  │         base top            │  ← płaska platforma 3mm
  │  ┌───────────────────────┐  │
  │  │                       │  │  ← hollow (puste wewnątrz)
  │  │                       │  │  ← ścianki 1.2-1.6mm
  │  │      9 mm ścianka     │  │
  │  │                       │  │
  │  └───────────────────────┘  │
  │  taper 3mm (zbieżność 8-12°)│
  └──────┘             └────────┘
        ↘               ↙
         cutting edge 0.4mm (dół)

Wymiary:
  - Całkowita wysokość:     12 mm
  - Grubość ścianki:        1.2–1.6 mm (stała po całej wysokości)
  - Krawędź tnąca (dół):   0.4 mm (taper od 1.2mm do 0.4mm na dolnych 3mm)
  - Platforma górna (base): 3 mm flat
  - Fillet górny:           0.8–1.2 mm radius
```

**Algorytm generowania (model_agent.py):**
1. Parsuj `outer_contour` z SVG → lista punktów
2. Offset zewnętrzny +wall_mm (Shapely: `polygon.buffer(wall_mm)`) → outer shell
3. Offset wewnętrzny = original contour → inner hollow
4. Extrude obie ścieżki na `total_height` (12mm)
5. Taper dolne 3mm: liniowa interpolacja outer_bottom → cutting_edge (0.4mm)
6. Flat base top 3mm: solid cap
7. Fillet górnej krawędzi: promień 0.8mm

### 4.2 Plik stamp: `{slug}_{size}_stamp.stl`

```
Widok przekroju (bok):

  ╔═══════╗ ╔═══╗ ╔═══════╗  ← raised features (oczy, guziki, falbanki)
  ║       ║ ║   ║ ║       ║     wysokość relief: 2.0–2.5 mm
  ╚═══════╩═╩═══╩═╩═══════╝
  ████████████████████████████  ← base plate 3.0 mm
  ████████████████████████████

Wymiary:
  - Base plate:     3.0 mm (solid)
  - Relief height:  2.0–2.5 mm (raised features)
  - Total height:   5.0–5.5 mm
  - Contour:        outer pomniejszony o clearance 5mm (SVG) + clearance 0.35-0.45mm (3D)
```

**Algorytm generowania (model_agent.py):**
1. Parsuj `stamp_outline` z SVG (inner layer) → base contour
2. Extrude base_contour na `base_height` (3mm) = solid base
3. Dla każdej ścieżki w `<g id="stamp">`:
   - Parsuj kształt → polygon
   - Extrude z z=3mm na wysokość +relief_height (2.0-2.5mm)
   - Dodaj jako union do bazy
4. Top surface flat, fillet 0.5mm na górnych krawędziach features

### 4.3 Parametry (z product_types.yaml)

```yaml
cutter:
  wall_thickness:   1.2   # mm — grubość ścianki
  blade_thickness:  0.4   # mm — krawędź tnąca (dół)
  taper_height:     3.0   # mm — strefa zbieżności ostrza
  base_height:      3.0   # mm — platforma górna (base)
  total_height:     12.0  # mm — całkowita wysokość
  fillet_top:       1.0   # mm — zaokrąglenie górnej krawędzi
  clearance_3d:     0.40  # mm — luz cutter↔stamp w 3D modelu

stamp:
  base_height:      3.0   # mm — grubość podstawy
  relief_height:    2.0   # mm — wysokość reliefu
  fillet_features:  0.5   # mm — zaokrąglenie detali
```

---

## 5. Walidacja drukowalności (printability_validator.py)

Nowy moduł. Uruchamiany po wygenerowaniu SVG, przed model_agent.

### 5.1 Sprawdzenia SVG

```python
def validate_svg_printability(svg_path, size_mm) -> ValidationResult:
    """
    Sprawdza SVG pod kątem drukowalności FDM/MSLA.
    Zwraca: {valid: bool, warnings: list, errors: list, auto_fixed: bool}
    """
```

| Sprawdzenie | Kryterium | Akcja przy błędzie |
|-------------|-----------|-------------------|
| Zamknięte ścieżki | path kończy się Z | ERROR — odrzuć |
| Min szerokość elementu | ≥ 5mm (przy XS=50mm) | WARNING + auto-fix (thicken) |
| Kąt wklęsły | ≥ 25° | WARNING + auto-fix (round) |
| Circle fit | kształt mieści się w okręgu size_mm | ERROR — skaluj |
| Odizolowane detale | każdy element połączony z konturem | ERROR — usuń |
| Za dużo węzłów | max 200 punktów na ścieżkę | WARNING + simplify |

### 5.2 Sprawdzenia STL

```python
def validate_stl_printability(stl_path, config) -> ValidationResult:
    """
    Sprawdza STL pod kątem drukowalności.
    Używa trimesh jako podstawy.
    """
```

| Sprawdzenie | Kryterium | Źródło |
|-------------|-----------|--------|
| Manifold (watertight) | trimesh.is_watertight | standard |
| Objętość > 0 | trimesh.volume > 0 | normals OK |
| Min grubość ściany | ≥ 1.2mm | Creality 2025 |
| Brak non-manifold edges | trimesh check | Netfabb standard |
| STL w milimetrach | weryfikacja skali przez volume | eksport |

---

## 6. Algorytmy techniczne (implementacja)

### 6.1 Polygon offset — Shapely (NOWE)

**Zastępuje:** `_offset_contour()` w model_agent.py (centroid scaling — BŁĘDNY dla concave)

```python
from shapely.geometry import Polygon
from shapely.ops import unary_union

def offset_contour(points: list[tuple], offset_mm: float) -> list[tuple]:
    """
    Prostopadły offset konturu (join_style=round).
    offset_mm > 0 = rozszerz na zewnątrz
    offset_mm < 0 = zwęź do środka
    """
    poly = Polygon(points)
    buffered = poly.buffer(offset_mm, join_style='round', resolution=32)
    if buffered.is_empty:
        return points  # fallback
    return list(buffered.exterior.coords)
```

**Wymaganie:** `pip install shapely` (dodaj do requirements.txt)

### 6.2 Ear-clipping triangulation (NOWE)

**Zastępuje:** `_triangulate_flat()` w model_agent.py (fan — działa TYLKO dla convex)

```python
def triangulate_polygon(contour: list[tuple]) -> list[tuple[int,int,int]]:
    """
    Ear-clipping dla polygon concave (gwiazda, płatek śniegu, ludzik).
    Zwraca listę trójek indeksów: [(i0,i1,i2), ...]
    """
    # Implementacja: iteracyjne znajdowanie "uszu" (ears) i ich odcinanie
    # Ucho = wierzchołek v[i] taki że trójkąt v[i-1],v[i],v[i+1]
    # nie zawiera żadnego innego wierzchołka konturu
    # O(n²) — wystarczające dla max ~200 punktów konturu
```

Alternatywnie: `pip install mapbox-earcut` (szybsza implementacja C++).

### 6.3 Bezier sampling — 32 punkty (NAPRAWA)

**Obecny kod (BŁĘDNY):**
```python
for k in range(1, 9):   # ← tylko 8 punktów → kanciasty wydruk
```

**Poprawny:**
```python
BEZIER_SAMPLES = 32  # stała konfiguracyjna
for k in range(1, BEZIER_SAMPLES + 1):
```

### 6.4 Taper geometry — krawędź tnąca (NOWE)

```python
def build_taper_ring(contour, z_bottom, z_taper_end, wall_full, wall_edge):
    """
    Generuje pierścieniową siatkę trójkątów dla zbieżnej krawędzi tnącej.

    Profil:
      z_bottom     → wall_edge (0.4mm)  — dół (cutting edge)
      z_taper_end  → wall_full (1.2mm)  — góra tapera

    Użycie: dolne 3mm cuttera (taper_height z config)
    """
    # Liniowa interpolacja grubości ścianki po wysokości Z
    # outer_r(z) = base_r + (wall_full - wall_edge) * (z - z_bottom) / taper_height
```

---

## 7. Prompt Claude dla design_agent (NOWY)

### 7.1 Prompt outer contour (cutter silhouette)

```
You are an expert SVG designer for 3D-printed cookie cutters sold on Etsy.

Task: Generate ONE single closed SVG path representing the OUTER SILHOUETTE of a
"{topic}" cookie cutter.

Style requirements (mandatory):
- Cute kawaii cartoon style — chubby proportions, rounded features
- Think of popular Etsy cookie cutter shops (ThinkMeal, SweetAmbs style)
- Recognizable at small sizes (50–150mm)
- NO photorealistic details — clean cartoon outline only

Technical requirements (mandatory):
- ViewBox: 0 0 {size_mm} {size_mm}
- Shape must fit within a circle of diameter {size_mm * 0.90}mm centered at ({cx}, {cy})
- SINGLE closed path: exactly one M command, ends with Z
- NO subpaths, NO multiple M commands
- Minimum 15 anchor/control points for organic shapes
- No sharp concave angles < 25°
- Minimum feature width: {size_mm * 0.10}mm (e.g. ears, tail, legs)
- All coordinate values within [2, {size_mm-2}]
- Use C (cubic bezier) for smooth curves, L for straight edges

Output: ONLY the path `d` attribute value. No XML, no quotes, no explanation.
```

### 7.2 Prompt stamp details (inner features)

```
You are an SVG designer creating embosser details for a "{topic}" cookie stamp.

The outer cutter contour is: {outer_path_d}
ViewBox: 0 0 {size_mm} {size_mm}

Task: Generate SVG elements for the INNER STAMP DETAILS.
These will become raised relief features (2mm high) on the stamp.

For a {topic}, include:
{detail_description}  ← np. "face: 2 eyes, smile, eyebrow; 3 buttons on torso; ruffles on limbs"

Technical requirements:
- Each element must be a CLOSED path or circle
- All elements must fit within the stamp outline (outer contour inset by {clearance_mm}mm)
- Minimum element size: {size_mm * 0.07}mm (smaller details won't print)
- Maximum detail count: 12 elements (slicer performance)
- Use <circle> for round features (eyes, buttons)
- Use <path> for organic features (smile, ruffles, eyebrow)
- All paths closed (end with Z)

Output: SVG fragment with only the inner elements. No <svg> wrapper, no outer path.
Example format:
<circle id="eye_l" cx="25.0" cy="18.0" r="3.0"/>
<circle id="eye_r" cx="35.0" cy="18.0" r="3.0"/>
<path id="smile" d="M 25,25 Q 30,30 35,25 Z"/>
```

---

## 8. Struktura folderów produktu (po Fazie 6)

```
data/products/
└── {product_type}/          ← cutter | stamp | set
    └── {slug}/
        ├── meta.json         ← status, steps_completed, created_at
        ├── listing.json      ← title, description, tags, price
        ├── design.json       ← metadane SVG (shapes, mode, validation)
        ├── source/
        │   ├── XS.svg        ← compound SVG (outer + stamp layers), 50mm
        │   ├── S.svg         ← 60mm
        │   ├── M.svg         ← 75mm
        │   ├── L.svg         ← 90mm
        │   ├── XL.svg        ← 110mm
        │   └── XXXL.svg      ← 150mm
        ├── models/
        │   ├── XS_cutter.stl
        │   ├── XS_stamp.stl
        │   ├── S_cutter.stl
        │   ├── S_stamp.stl
        │   ├── M_cutter.stl
        │   ├── M_stamp.stl
        │   ├── L_cutter.stl
        │   ├── L_stamp.stl
        │   ├── XL_cutter.stl
        │   ├── XL_stamp.stl
        │   ├── XXXL_cutter.stl
        │   └── XXXL_stamp.stl
        ├── renders/
        │   ├── hero.jpg        ← 2000×2000, białe tło, oba elementy zestawu
        │   ├── lifestyle.jpg   ← kontekst kuchenny, ciasto w tle
        │   ├── sizes.jpg       ← wszystkie 6 rozmiarów obok siebie
        │   ├── detail.jpg      ← zbliżenie na krawędź tnącą i relief
        │   └── info.jpg        ← wymiary, materiał, instrukcja pielęgnacji
        └── listing_export.json ← pełny listing Etsy (dry-run)
```

---

## 9. Slicer settings (dla referencji w listingu)

Ustawienia rekomendowane w opisie produktu na Etsy:

```
Materiał:     Food-safe PLA lub PETG
Dysza:        0.4 mm (standardowa)
Grubość warstwy: 0.2 mm
Grubość ścian:  1.2 mm (3 perimetry przy dyszy 0.4mm)
Warstwy górne:  3–4 warstwy
Infill:         20% (wystarczające dla cutterów)
Temperatura:    PLA 200–210°C / PETG 230–240°C
Podpora:        NIE wymagana (geometria zoptymalizowana)
Orientacja:     Krawędź tnąca SKIEROWANA KU GÓRZE (lepsze surface finish)
```

---

## 10. Zależności (requirements.txt)

Nowe zależności wymagane przez Fazę 6:

```
shapely>=2.0.0        # polygon offset (prostopady, join_style=round)
mapbox-earcut>=1.1.6  # triangulacja concave polygons (opcjonalne, fallback własna impl.)
```

---

*Wersja: 1.0 | Data: 2026-03-11 | Autor: Claude (architect v2)*
*Plik dla agentów AI — używaj jako context przy pracy nad design_agent.py i model_agent.py*
