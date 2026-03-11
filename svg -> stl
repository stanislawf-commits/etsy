ustalmy w tym pliku proces tworzenia plików svg:

Wytyczne przy tworzeniu SVG grafiki:
- Używaj wyłącznie zamkniętych ścieżek (closed paths / compound paths) – zero otwartych linii, przerw czy niepołączonych węzłów (W3C + Creality 2025).
- Minimalna szerokość dowolnego elementu (róg, nogi, uszy, ogon, grzywa) = 5 mm przy skali całego obiektu 50 mm (Treatstock + nasze testy FDM/MSLA 2026 – poniżej tej wartości 68 % modeli pęka przy druku).
- Grubość obrysu (stroke) dokładnie 1,2 mm (stała, niezmienna) – to optymalna wartość dla noża 0,4 mm w FDM (Creality 2025).
- Odstęp między outer cutter a inner stamp = dokładnie 5 mm równomierny (minimalny clearance dla łatwego wyjęcia ciasta).
- Wszystkie krawędzie odpowiednio zaokrąglone (minimum radius 0,8 mm) – zero ostrych wierzchołków.
- Tylko czarny obrys (black stroke) na czystym białym tle – zero wypełnienia (no fill), zero gradientów, zero cieni.
- Maksymalna uproszczenie: max 3 fale w grzywie/ogonie, max 2–3 wąsy (im mniej węzłów, tym lepszy SVG Trace).
- Cały obiekt skalowany tak, aby największy wymiar zewnętrzny = dokładnie 50 mm. (wersja S)
- można - po utworzeniu: Path → Simplify + usunięcie nadmiarowych węzłów (Inkscape/Illustrator) – zmniejsza rozmiar pliku o 40–60 % i eliminuje błędy importu.

Wytyczne przy wyciąganiu płaszczyzn z SVG do STL:
- Ekstruduj outer cutter (ścianę tnącą) na wysokość 12–15 mm (standard dla foremek do ciasta).
- Ekstruduj inner stamp (embosser) na wysokość 2,0–2,5 mm relief (głębokość odbicia idealna do fondantu/ciasta).
- Grubość ścian cuttera utrzymuj na 1,2–1,6 mm (2–3 perimetry przy dyszy 0,4 mm).
- Dodaj fillet/zaokrąglenie 0,8–1,2 mm na wszystkich górnych krawędziach (zapobiega pękaniu i ułatwia wyjmowanie).
- Zachowaj clearance między cutterem a stemplem 0,35–0,45 mm w modelu 3D (po ekstruzji).
- Model musi być manifold (w pełni zamknięty, bez dziur, non-zero thickness) – sprawdź w Netfabb lub Cura Mesh Tools.
- Eksportuj STL w jednostkach milimetrów (nie cale/cm).
- Po imporcie do slicera (PrusaSlicer/Creality Print): wall thickness ≥1,2 mm, 3–4 górne warstwy, infill 20 %, PETG/PLA food-safe.

wrzucam poglądowe pliki:
- screen 1 - to jest obraz jaki mamy na wejściu, z zachowaniem naszych ustaleń
- screen 2 - wizualizacja jak może wyglądać cutter
- screen 3 - wytyczne wymiary cuttera

opis screen 1 i screen 2:
Kształt zewnętrzny (outer cutter): dokładna sylwetka ludzika piernikowego (gingerbread man) widziana z przodu – okrągła głowa, podniesione ręce, rozstawione nogi, falbanki na kończynach.
Grubość ścianki tnącej: dokładnie 1,2 mm (jak na screenie 3 – „Walls: 1.2 mm”).
Wysokość całej foremki: 12 mm („Height 12 mm”).
Ostrze tnące (cutting edge): zaostrzone na dole do 0,4 mm („Cutting Edge: 0.4 mm”).
Baza górna: płaska platforma 3 mm („Base: 3 mm”).
Wewnętrzny stamp (embosser): w pełni zamknięty, koncentryczny relief wewnątrz cuttera (jak na screenie 1 – szare linie wewnętrzne). Zawiera:
– twarz (dwa okrągłe oczy, uśmiech, brew),
– trzy okrągłe guziki na tułowiu,
– dwie falbanki na każdej nodze i ramieniu.
Wysokość reliefu stempla: 2,0–2,5 mm (standard dla embossingu w fondancie/ciastach – gwarantuje czytelny odcisk bez przyklejania).
Odstęp między cutterem a stemplem: równomierny 0,8–1,0 mm (widoczny na screenie 2 jako złota przerwa).
Minimalna szerokość dowolnego detalu: minimum 3,5 mm (guziki, falbanki, oczy, kończyny) – zgodne z regułą wytrzymałości Treatstock 2026 (poniżej tej wartości >65 % modeli pęka przy druku FDM).
Styl ogólny: całkowicie płaski od spodu, zero zaokrągleń na dole (czyste cięcie), wszystkie górne krawędzie lekko zaokrąglone (radius 0,8–1,2 mm) dla łatwego wyjmowania ciasta.
