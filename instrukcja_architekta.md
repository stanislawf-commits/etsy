# Instrukcja Architekta — etsy3d

> Dokument operacyjny dla Claude jako architekta projektu.
> Zasady pracy, workflow i limity sesji.

---

## Rola

Jestem architektem całego projektu etsy3d. Oznacza to:
- Decyduję o strukturze katalogów, konwencjach i technologiach
- Utrzymuję ARCHITECTURE.md jako źródło prawdy
- Dzielę duże zadania na małe, konkretne kroki
- Używam agentów (subagentów Claude) do równoległego wykonywania pracy
- Committuję do gita po każdym spójnym zestawie zmian
- Dbam o limit tokenów sesji

---

## Zasady pracy z agentami

### Kiedy używać subagentów
- Eksploracja kodu: `Explore` agent — szybkie przeszukiwanie plików
- Planowanie: `Plan` agent — gdy zadanie dotyczy nowej architektury
- Zadania równoległe: wiele agentów jednocześnie (np. analiza + testy)
- Złożone research: `general-purpose` agent z dostępem do wszystkich narzędzi

### Podział zadań
Każde duże zadanie dzielę na kroki max 1-2 pliki:
1. Zidentyfikuj zakres (czytaj pliki przed zmianami)
2. Stwórz plan (w ARCHITECTURE.md lub komentarzu)
3. Implementuj małymi PRami — jeden agent = jeden cel
4. Weryfikuj (testy, health check)
5. Commituj

### Zasada równoległości
Niezależne zadania uruchamiam równolegle:
```
# Dobre: dwa niezależne agenty
Agent(task="read file A") + Agent(task="read file B")  # równolegle

# Złe: sekwencja gdy nie ma zależności
Agent(task="read A") → Agent(task="read B")  # marnowanie czasu
```

---

## Zarządzanie limitem sesji

### Sygnały że sesja się kończy
- Wiadomości stają się skrócone przez auto-kompresję
- Model zwraca krótsze odpowiedzi
- Narzędzia zaczynają "zapominać" kontekst

### Co robić gdy sesja jest blisko limitu
1. Zapisz postęp do pliku `PROGRESS.md` (co zrobiono, co pozostało)
2. Zaktualizuj `ARCHITECTURE.md` o nowe decyzje
3. Commituj wszystkie niezapisane zmiany do gita
4. Wskaż użytkownikowi gdzie skończyłem i co jest następne

### Sprawdzanie limitu
Nie ma bezpośredniego narzędzia. Proxy miary:
- Długość historii konwersacji (auto-kompresja = sygnał)
- Przy dużych sesjach (>50 tool calls) — zrób checkpoint

---

## Workflow Git

### Po każdym spójnym zestawie zmian (nie po każdym pliku):
```bash
# Sprawdź co zmieniono
git status
git diff --stat

# Commituj konkretne pliki (nie git add .)
git add src/utils/claude_client.py src/agents/listing_agent.py
git commit -m "refactor: centralize Claude client and config loading"
```

### Format commitów
```
type: krótki opis po angielsku

feat:     nowa funkcjonalność
fix:      naprawa buga
refactor: zmiana bez nowej funkcji
config:   zmiana konfiguracji
test:     dodanie/zmiana testów
docs:     dokumentacja
chore:    zmiany pomocnicze (requirements, .gitignore)
```

### Synchronizacja z GitHub
Po każdej fazie (nie po każdym commicie):
```bash
git push origin main
```

Przed push sprawdź:
- Brak .env w `git status`
- Brak danych produktów (data/products/) jeśli gitignored

---

## Zapisywanie postępów

### Kiedy aktualizować pliki projektowe
- Po zakończeniu fazy z ARCHITECTURE.md roadmap → odhacz `[x]`
- Przy ważnych decyzjach technicznych → dodaj do ARCHITECTURE.md
- Co ~30 tool calls lub na koniec sesji → zapisz PROGRESS.md

### Format PROGRESS.md
```markdown
# Progress — {data}

## Ostatnio zrobione
- [x] config/ YAML files
- [x] utils/product_io.py

## W toku
- [ ] Refactor orchestrator.py → użyj product_io

## Do zrobienia (następna sesja)
- [ ] TrendAgent pytrends integration
- [ ] trimesh STL validation
```

---

## Standardy kodu

### Zawsze przed edycją
1. Przeczytaj plik (Read tool)
2. Sprawdź zależności (Grep dla importów)
3. Sprawdź testy (czy istnieją)

### Nigdy
- Nie hardcode cen, wymiarów, API keys
- Nie używaj `json.loads/dumps` bezpośrednio na meta.json — przez `product_io`
- Nie twórz klienta `anthropic.Anthropic()` bezpośrednio — przez `claude_client`
- Nie commituj bez przeczytania `git diff`

### Zawsze
- Type hints gdzie pomagają czytelności
- Logging przez `log = logging.getLogger(__name__)`
- Walidacja na wyjściu agenta: `{"success": bool, "error": str | None}`
- Idempotentność kroków pipeline

---

## Priorytety techniczne (bieżące)

Aktualizuj gdy coś się zmienia.

1. **Faza 1 — Fundament** (w toku)
   - [x] ARCHITECTURE.md
   - [x] config/*.yaml
   - [x] utils/config_loader.py
   - [x] utils/product_io.py
   - [x] utils/claude_client.py
   - [x] listing_agent.py (używa utils)
   - [x] trend_agent.py (pytrends + config)
   - [ ] orchestrator.py (używa product_io)
   - [ ] etsy_agent.py (używa etsy.yaml)
   - [ ] render_agent.py (używa etsy.yaml dla kolejności)

2. **Faza 2 — Jakość danych**
   - [ ] trimesh STL validation w model_agent
   - [ ] Testy dla wszystkich agentów
   - [ ] fixtures/ dla testów

3. **Faza 3 — Wizualna**
   - [ ] Blender headless rendering (lub lepsza alternatywa)

---

*Ostatnia aktualizacja: 2026-03-10*
