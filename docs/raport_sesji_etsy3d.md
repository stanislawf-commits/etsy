# ETSY3D — Raport sesji startowej
**Data:** 2026-03-10 | **Wersja:** 0.1.0 | **Status:** MVP GOTOWY

---

## 1. Cel projektu

Autonomiczny pipeline: temat → listing Etsy z produktem drukowanym w 3D.

- **Wejście:** temat (np. "floral wreath")
- **Wyjście:** folder produktu z `listing.json` + `meta.json` + treść SEO gotowa do Etsy
- **Docelowo:** pełna automatyzacja od SVG → STL → render → publikacja → druk

---

## 2. Infrastruktura po sesji

| Komponent | Status | Szczegóły |
|-----------|--------|-----------|
| Linux PC (Dell Latitude) | ✅ DONE | Ubuntu, Python 3.11, Node.js 20, Git 2.43 |
| Claude Code CLI | ✅ DONE | Zainstalowany via install.sh, auth przez claude.ai |
| GitHub repo | ✅ DONE | `github.com/stanislawf-commits/etsy` (private) |
| SSH na PC | ✅ DONE | OpenSSH server, IP: `192.168.2.110` |
| Projekt etsy3d | ✅ DONE | Struktura folderów, `.env.example`, `requirements.txt` |
| Git sync | ✅ DONE | 3 commity, push działa, `.gitignore` chroni klucze API |
| Klucz Anthropic API | ✅ DONE | Nowy klucz w `.env` (lokalnie), stary unieważniony |

---

## 3. Zbudowane komponenty

| Agent / Moduł | Status | Co robi |
|---------------|--------|---------|
| `TrendAgent` | ✅ DONE | 10 tematów evergreen + Q4 holiday, `suggest()` → `list[dict]` |
| `ListingAgent` | ✅ DONE | Claude API: tytuł SEO, opis 300+ słów, 13 tagów, cena EUR |
| `Orchestrator` | ✅ DONE | `run_pipeline(topic, type, size)` → folder + `listing.json` |
| `cli.py` | ✅ DONE | Komendy: `new-product`, `health`, `status`, `list` |
| `DesignAgent` | ❌ TODO | Generowanie SVG przez DALL-E 3 |
| `ModelAgent` | ❌ TODO | SVG → STL (FreeCAD/OpenSCAD headless) |
| `RenderAgent` | ❌ TODO | Rendery 3D, mockupy produktowe (Blender) |
| `EtsyAgent` | ❌ TODO | Publikacja listingu przez Etsy API v3 |

---

## 4. Wynik testu pipeline

```bash
python3 cli.py new-product "floral wreath"
```

| Pole | Wynik |
|------|-------|
| Slug | `floral-wreath-cutter-m` |
| Tytuł SEO | "Floral Wreath Cookie Cutter - Medium 3D Printed PLA..." (121 znaków) |
| Cena | 11.5 EUR (zakres 8–15 EUR dla cutter M) |
| Tagi | 13 tagów, każdy max 20 znaków |
| `listing.json` | `data/products/floral-wreath-cutter-m/listing.json` |
| `meta.json` | `status=draft`, `created_at`, `id`, `topic` |

---

## 5. Struktura projektu

```
~/etsy3d/
├── src/
│   ├── agents/
│   │   ├── trend_agent.py       ✅
│   │   └── listing_agent.py     ✅
│   ├── pipeline/
│   │   └── orchestrator.py      ✅
│   └── utils/
├── config/
├── data/products/               ← foldery produktów (gitignore)
├── data/templates/
├── logs/
├── docs/
├── tests/
├── cli.py                       ✅
├── requirements.txt             ✅
├── .env.example                 ✅
├── .env                         ✅ (lokalnie, nie w git)
└── CLAUDE.md                    ✅
```

---

## 6. Roadmapa kolejnych sesji

| Sesja | Zadanie | Opis |
|-------|---------|------|
| 2 | DesignAgent | DALL-E 3 → grafika 2D → SVG (wymaga `OPENAI_API_KEY`) |
| 2 | ModelAgent | SVG → STL via FreeCAD/OpenSCAD headless, rozmiary S–XXL |
| 3 | RenderAgent | Blender headless: render white bg + lifestyle mockup |
| 3 | EtsyAgent | Etsy API v3: draft listing, upload zdjęć, publikacja |
| 4 | Auto-pipeline | Pełny flow: temat → STL → render → listing Etsy |
| 5+ | Bambu Lab | Auto-druk po zamówieniu, etykiety, Home Assistant IoT |
| 5+ | Shopify | Migracja sklepu, własne strategie marketingowe |

---

## 7. Potrzebne klucze API do następnej sesji

```bash
# Dodaj do ~/etsy3d/.env
OPENAI_API_KEY=        # platform.openai.com — DALL-E 3 (~$5 na start)
ETSY_API_KEY=          # developer.etsy.com → Create App
ETSY_API_SECRET=       # jw.
ETSY_SHOP_ID=          # numer w URL Twojego sklepu Etsy
```

> ⚠️ Nigdy nie wklejaj kluczy API w czacie ani na GitHubie.

---

## 8. Komendy startowe — następna sesja

```bash
# Synchronizacja z GitHub
cd ~/etsy3d && git pull origin main

# Sprawdź stan środowiska
python3 cli.py health

# Uruchom Claude Code
claude

# Test pipeline
python3 cli.py new-product "mountain climbing"
```

---

## 9. Ważne adresy

| Co | Gdzie |
|----|-------|
| GitHub repo | `github.com/stanislawf-commits/etsy` |
| PC lokalnie (SSH) | `ssh dell@192.168.2.110` |
| Anthropic Console | `console.anthropic.com/settings/keys` |
| Etsy Developer | `developer.etsy.com` |

---

*Raport wygenerowany: 2026-03-10 | Architekt: Claude Sonnet 4.6*
