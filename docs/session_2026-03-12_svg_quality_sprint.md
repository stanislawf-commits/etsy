# Sesja 2026-03-12 — SVG Quality Sprint (DALL-E+potrace pipeline)

## Cel sesji
Budowa i debugowanie pipeline'u DALL-E 3 → ImageMagick → potrace → SVG
jako alternatywy dla generowania SVG przez Claude API (tryb `real`).

## Zmiany w kodzie (src/agents/design_agent.py)

### Nowe elementy
- `DALLE_PROMPTS` — słownik 14 tematów z promptami anty-3D, coloring book style
- `_DALLE_DEFAULT` — fallback prompt dla nieznanych tematów
- `_make_svg_dalle_potrace()` — pełny pipeline DALL-E+potrace
- Tryb `mode='dalle'` w klasie `DesignAgent.__init__`
- Importy: `subprocess`, `tempfile`, `urllib.request` (dodane na górze pliku)

### Naprawione bugi (tryb `real` / Claude API)
- `_validate_path`: usunięto check single-subpath, zastąpiono balansem M/Z
- `max_tokens` 1024 → 2048 (fix truncation złożonych kształtów)
- `SHAPE_HINTS` — 14 wskazówek wizualnych per temat

### Naprawione bugi (tryb `dalle` / potrace)
| bug | fix |
|-----|-----|
| Koordynaty out-of-bounds (x=2003) | viewBox × 10 zamiast / 10 |
| Podwójne skalowanie w transform | `scale(1,-1)` zamiast `scale(sx,-sy)` |
| stroke-width=460mm | stała `stroke_w=1.5` mm |
| Walidacja zbyt restrykcyjna (-16.3) | margin 3× size_mm |
| PNG znikał po przetwarzaniu | zapis do `source/{size}_dalle_raw.png` przed tempfile |
| fill=none (niewidoczny kształt) | fill="white" + fill-rule="evenodd" |
| Morphology Dilate/Erode niszczyło obraz | usunięte z ImageMagick pipeline |
| Walidacja potrace format spacje | coords regex akceptuje spacje i przecinki |

### Aktualne parametry potrace pipeline
```python
# ImageMagick
-crop 920x920   -blur 0x0.4   -threshold 60%   -negate   -type Bilevel

# potrace
--turdsize 40   --alphamax 1.5   --opttolerance 0.8

# SVG output
transform="translate(0,{size_mm}) scale(1,-1)"
fill="white"   fill-rule="evenodd"   stroke-width="1.5"
```

## Wyniki testów

| slug | nodes | potrace | SVG size | uwagi |
|------|-------|---------|----------|-------|
| test-floral-v3 | 750 | True | 71 KB | stare parametry, za dużo detali |
| test-floral-v4 | 112 | True | 12 KB | turdsize=40, dobry rozmiar |
| test-floral-v5 | 418 | True | 3.8 KB | y-flip fix, stroke fix |
| test-floral-v6 | 1153 | True | 118 KB | threshold=60%, za dużo detali |

## Status na koniec sesji

✅ Pipeline technicznie działa (potrace=True, bez fallbacku)
🟡 Jakość wizualna SVG nieznana — do weryfikacji w przeglądarce
🟡 Parametry ImageMagick wymagają fine-tuningu (threshold vs nodes)
❌ Brak kredytów Anthropic API (tryb `real` niedostępny)

## Następne kroki

1. Ocena wizualna test-floral-v6/XS.svg w Firefox
2. Dostrojenie threshold (cel: nodes 100-400, rozmiar <20KB)
3. Test 3 różnych tematów (halloween ghost, cottagecore mushrooms, hearts)
4. Regeneracja 22 produktów XS z DALL-E+potrace
5. Rebuild STL po nowych SVG
6. Uzupełnienie kredytów Anthropic (opcjonalne — pipeline działa bez nich)

## Commity tej sesji

- `fix(svg): kawaii shape hints + multi-subpath prompts + system prompt` (a6bc17f)
- `feat(svg): regenerate all 22 products with kawaii multi-subpath SVG` (e1c28c6)
- `fix(svg): potrace coordinate scaling x10 fix + anti-3D prompts + PNG persistence` (cc13a0d)
- `fix(svg): potrace pipeline v2 — fill/transform/stroke/validation fixes` (ten commit)
