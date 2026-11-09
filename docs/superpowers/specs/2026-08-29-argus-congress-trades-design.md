# Argus — Increment: transakcje giełdowe członków Kongresu USA

**Data:** 2026-08-29
**Wersja:** v2 (po ponownej analizie pod kątem samonauki — patrz sekcja 13)
**Status:** ⛔ **ZABLOKOWANY — nie implementować w tej formie.** Niezależna recenzja (2026-08-29) wykazała, że rdzeń scoringu Argusa nie potrafi ocenić źródła o horyzoncie 30d i niskim bazowym hit-rate. Wymagany warunek wstępny: increment kalibracji scoringu. Szczegóły i lista poprawek — sekcja 14.
**Kontekst:** rozszerzenie Argusa o nowy typ źródła — ujawnienia transakcji giełdowych kongresmenów (STOCK Act). Punkt wyjścia: pytanie o monitoring portfela Nancy Pelosi, rozszerzone przez użytkownika na cały Kongres.

## 1. Problem

Argus mierzy wiarygodność źródeł przez falsyfikowalne twierdzenia kierunkowe (claim) rozliczane względem ceny. Kongresmeni publikują swoje transakcje giełdowe w ramach STOCK Act — to gotowe, ustrukturyzowane twierdzenia kierunkowe od źródeł o potencjalnej przewadze informacyjnej. Argus ich dziś nie zbiera.

Pytanie, na które ma odpowiadać ten increment: **którzy kongresmeni faktycznie mają przewagę, mierzoną tą samą miarą co każde inne źródło w Argusie** — a nie „co kupiła Pelosi".

Z tego wynika kryterium sukcesu, które w v1 zostało przeoczone: **pętla nauki musi się domykać**. Źródło, które nigdy nie uzbiera dość claimów, żeby dostać ocenę, jest dla tego projektu bezwartościowe niezależnie od jakości pojedynczego sygnału.

## 2. Decyzje podjęte przez użytkownika

| Decyzja | Wybór | Uzasadnienie |
|---|---|---|
| Zakres | Cały Kongres (House + Senate), nie tylko Pelosi | Scoring ma sam wyłonić wiarygodnych; ograniczanie do jednego nazwiska z góry przesądza wynik |
| Kotwica `entry_price` | **Data ujawnienia** (`filing_date`), nie data transakcji | Brak look-ahead biasu — claim musi być czymś, co dało się zagrać |
| Uniwersum aktywów | Auto-dodawanie, uniwersum ograniczone popularnością tickera | Uniknięcie 858 tickerów w `assets` bez duszenia liczby claimów |
| Filtr claimów | **Brak progu kwotowego** — każda transakcja w uniwersum | Warunek domknięcia pętli nauki (sekcja 4) |
| Horyzonty | Tylko `30d` | Zgodnie z istniejącym wzorcem dla `insider` w `evaluator.py` (sekcja 6) |
| Alerty | Brak w tym incremencie — tylko baza + ranking | Próg alertu bez danych = spam albo cisza |
| Widok „net aktywności per filer" | Osobny increment, po zebraniu scoringu | Budowanie UI do śledzenia ludzi, o których nic jeszcze nie wiadomo, jest przedwczesne |
| Podejście | A: kolektor w kształcie `insider.py`, bez nowej tabeli | Maksymalny reuse, zerowe ryzyko regresji |

## 3. Źródło danych — stan zweryfikowany empirycznie (2026-08-29)

Wszystkie poniższe sprawdzone realnym żądaniem HTTP, nie z pamięci:

| Źródło | Wynik | Werdykt |
|---|---|---|
| `raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data/trades.json` | HTTP 200, 4.37 MB, JSON | **wybrane** |
| `house-stock-watcher-data.s3...amazonaws.com` | HTTP 403 | martwe |
| `senate-stock-watcher-data.s3...amazonaws.com` | HTTP 403 | martwe |
| `bff.capitoltrades.com` | HTTP 503 (bot-block) | odpada |
| `lambdafin.com/api/congressional/recent` | HTTP 200, pusta lista | bezużyteczne |
| quiverquant / EODHD | płatne | poza zakresem |

**Charakterystyka feedu** (pomiar na pobranej kopii):

- 5000 rekordów, okno kroczące: `filing_date` 2026-07-01 → 2026-08-27
- `branch`: 2880 `executive` (w tym 2708 wierszy Donald J Trump), 2120 `congress`
- `chamber`: 1080 house, 1040 senate
- `id` unikalne 2120/2120; `filer_id`, `filing_date`, `amount_range_low` — zero wartości pustych
- Pola: `id, source_id, transaction_date, filing_date, owner, ticker, asset_name, asset_type, transaction_type, amount_range_low/high/label, days_to_file, is_late, filer_id, filer_name, branch, chamber, party, state, office, doc_url, filing_type`
- Typy transakcji: `Purchase` (2606), `Sale (Full)` (2111), `Sale (Partial)` (272), `Exchange` (11)
- Przedziały kwotowe: zamknięty zbiór 8 etykiet, od `$1,001 - $15,000` do `$5,000,001 - $25,000,000`

**Potwierdzenie opóźnienia ujawnień:** Pelosi, 5 transakcji w oknie — INTC i BE za $0.5–5M, transakcja 2026-07-24, ujawnienie 2026-08-21. 28 dni różnicy. To jest empiryczne uzasadnienie decyzji o kotwiczeniu w `filing_date`.

## 4. Dobór filtrów — pod moc statystyczną, nie pod czystość dashboardu

To jest sekcja, która w v1 była błędna. Zostawiam ślad rozumowania, bo błąd jest pouczający.

**Błąd v1:** ustawiłem jeden próg kwotowy (`amount_range_low >= $50k`), który pełnił jednocześnie dwie role — ograniczał uniwersum aktywów i decydował, które transakcje stają się claimami. Optymalizowałem go pod niski szum i czytelny dashboard. Skutek dla nauki:

| Wariant | aktywa | claimy/60d | mediana claimów na filera | filerów ≥20 claimów |
|---|---|---|---|---|
| **próg $50k (v1)** | 42 | **57** | **1** | **1** |
| uniwersum ≥3 filerów, bez progu | 70 | 445 | 3 | 6 |
| **hybryda (v2)** | 93 | **481** | 3 | **7** |

`scorer.py` przyznaje ocenę dopiero od 5 claimów (`argus_grade(..., min_claims=5)`). Przy wariancie v1 mediana wynosiła **1 claim na filera**, a tylko jeden filer przekraczał 20. Przy jednym horyzoncie (`30d`) to jeden outcome na claim — czyli **większość źródeł kongresowych zostałaby na ocenie „?" przez lata**. Feature zbierałby dane i nie uczył się niczego.

**Drugi błąd v1:** odrzuciłem klauzulę konsensusu („ticker tknięty przez ≥N kongresmenów") jako słaby **sygnał** — bo wyławia MSFT/AAPL trzymane przez pół Kongresu w koszykach indeksowych. To prawda, ale nieistotna: właściwą rolą tej klauzuli jest bycie **ogranicznikiem uniwersum**, gdzie selekcjonuje dokładnie to, co trzeba — płynne, mainstreamowe tickery, które yfinance obsługuje bez problemu. Dwa różne pytania, w v1 odpowiedziałem na niewłaściwe.

**Rozwiązanie v2: rozdzielić oba filtry.**

*Filtr uniwersum* (ogranicza koszt — liczbę aktywów i wywołań yfinance). Ticker wchodzi do `assets`, gdy w bieżącym oknie feedu:
- tknęło go **≥3 różnych filerów**, **lub**
- ma choć jedną transakcję o `amount_range_low >= $50 000`

→ **93 aktywa**

*Filtr claimów* (ogranicza jakość): **żadnego progu kwotowego**. Każda transakcja kongresowa w tickerze należącym do uniwersum tworzy claim.

→ **481 claimów / 60 dni**, **20 z 51 filerów przekracza próg oceny już po pierwszym oknie**

Kwota nie znika z systemu — steruje `confidence` (sekcja 6), ale nie decyduje o istnieniu claimu.

**Projekcja roczna dla czołówki** (×6 okien 60-dniowych): Alan Armstrong ~540, Tuberville ~432, Khanna ~294, Rulli ~180, McCaul ~144, Boozman ~108. Przy takich liczbach ranking per nazwisko zaczyna cokolwiek znaczyć.

**Kontrola wobec pierwotnego pytania:** Pelosi ma w tym uniwersum 4 claimy na okno (~24/rok) — wariant hybrydowy został wybrany m.in. dlatego, że klauzula `≥$50k` wciąga jej duże zakupy BE, którego poza nią nie tyka nikt. Ograniczenie się do samej popularności tickera dałoby jej 2. Zastrzeżenie w sekcji 12.

**Efekt uboczny do zaakceptowania:** popularność tickera liczona jest w obrębie pobranego okna, więc bywa zmienna. Ticker z 2 filerami dziś może mieć 3 jutro — wtedy jego wcześniejsze transakcje (wciąż obecne w oknie) utworzą claimy z `entry_ts` w przeszłości. To nie jest look-ahead: `filing_date` faktycznie jest momentem upublicznienia, a cena wejścia jest historyczna względem niego.

## 5. Architektura

Bez nowych tabel i bez migracji. Increment reużywa istniejący pipeline w całości.

```
congress feed (JSON, GET, bez klucza)
   ↓ filtr uniwersum (popularnosc tickera lub duza transakcja)
   ↓ filtr wiersza (branch, ticker, typ)
Source(kind="congress", handle="congress:<filer_id>")   ← per polityk
   ↓
Item (external_id = feed.id)  →  Claim(method="congress")  +  ClaimAudit
   ↓
Outcome Evaluator — wylacznie horyzont 30d  →  Source Scorer
   ↓
/api/sources (ranking)  ·  /api/assets (overview)
```

**Source per polityk** — nie jeden zbiorczy „Congress". To warunek konieczny, żeby scoring odpowiedział na pytanie z sekcji 1: ranking wiarygodności powstaje per nazwisko. Source powstaje leniwie, tylko dla filerów mających kwalifikujący się wiersz (51 w oknie).

**Nowe pliki:**

- `argus/collectors/congress.py`
- `tests/test_congress.py`
- `tests/fixtures/congress_sample.json` (zamrożona próbka realnego feedu)

**Zmieniane pliki:**

- `argus/main.py` — funkcja `_congress_job()` + `sched.add_interval("congress", _congress_job, minutes=1440)`
- `argus/evaluator.py` — jedna linia w `HORIZONS_BY_METHOD`: `"congress": {"30d"}`

**Bez zmian:** `models.py`, `api.py`, frontend, `db-init`. Nowe źródła trafiają do istniejącego rankingu `/api/sources`, nowe aktywa do overview — automatycznie.

## 6. Reguły przetwarzania

**Filtr wejściowy** — wiersz jest pomijany, gdy:

- `branch != "congress"` (odcina 2880 wierszy branży wykonawczej, w tym Trumpa)
- `ticker` pusty lub nie pasuje do `^[A-Z]{1,5}$` (obligacje komunalne, LLC, fundusze, noty strukturyzowane)
- `asset_type` zawiera „option" (feed nie podaje call/put ani strike, więc kierunku nie da się uczciwie ustalić; 22 wiersze w oknie)
- `transaction_type == "Exchange"` (kierunek niejednoznaczny; 9 wierszy)
- ticker nie należy do uniwersum wyliczonego w sekcji 4

**Mapowanie kierunku:**

| `transaction_type` | `direction` |
|---|---|
| `Purchase` | `bull` |
| `Sale (Full)`, `Sale (Partial)` | `bear` |

Sprzedaże są zachowane mimo że bywają rebalansowaniem lub optymalizacją podatkową. Ich wycięcie odrzuciłoby ~35% danych i wprowadziło bias w stronę wyłącznie sygnałów byczych — a scoring i tak zweryfikuje, czy sprzedaże danego filera cokolwiek przewidują.

**Confidence** — z przedziału kwotowego, po jednym stopniu na każdą z 8 etykiet feedu:

| przedział | confidence |
|---|---|
| $1k–15k | 0.45 |
| $15k–50k | 0.48 |
| $50k–100k | 0.50 |
| $100k–250k | 0.55 |
| $250k–500k | 0.58 |
| $500k–1M | 0.60 |
| $1M–5M | 0.63 |
| $5M–25M | 0.65 |

Zakres identyczny z `insider.py` (0.45–0.65). Kongresmen nie dostaje na starcie priorytetu nad insiderem korporacyjnym — o hierarchii decyduje scoring, nie założenie projektanta.

**Horyzont oceny:** wyłącznie `30d`, przez wpis `HORIZONS_BY_METHOD["congress"] = {"30d"}` w `evaluator.py`.

Bez tego wpisu metoda wpada w fallback „wszystkie horyzonty", co byłoby błędem gorszym niż szum. `entry_ts` pochodzi z `filing_date`, które nie ma składowej czasu — czyli jest północą — a `get_historical_price` zwraca dzienny close. Horyzont 1h wyceniałby więc **ten sam close co wejście**: zwrot dokładnie 0, przy progu `THRESHOLDS["1h"] = 0.005` każdy claim byczy zaliczany jako pudło. To systematyczne zaniżanie hit-rate, nie losowy szum. `evaluator.py` rozwiązał już ten problem dla `insider` (`{"30d"}`, z komentarzem „1h/24h/7d would just be noise + leakage") — `congress` idzie tym samym torem.

**Pola claimu:**

- `method = "congress"`
- `entry_ts = filing_date`
- `entry_price = get_historical_price(asset, filing_date)`
- `status = "open"`

**Auto-dodawanie aktywa:** przed utworzeniem claimu, `Asset(symbol=ticker, kind="stock", yf_symbol=ticker, scorable=True)`. Warunek: yfinance musi zwrócić cenę historyczną. Jeśli nie zwróci — wiersz jest pomijany i **aktywo nie powstaje**, żeby tabela `assets` nie zapełniała się martwymi symbolami.

**Kolejność operacji** jest wymuszona przez klucz obcy `claims.asset -> assets.symbol`: aktywo musi istnieć i mieć cenę zanim powstanie claim.

**Idempotencja:** `external_id = feed.id`, złapane przez istniejący `UniqueConstraint(source_id, external_id)` na `items`. Powtórny przebieg na tym samym feedzie tworzy zero nowych claimów.

## 7. Obsługa błędów

Wzorzec z `insider.py` i `_edgar_job()`:

- feed nieosiągalny lub niepoprawny JSON → `logger.warning`, `return 0`, job kończy się czysto
- brak ceny z yfinance dla tickera → pominięcie wiersza, bez tworzenia aktywa
- wyjątek na pojedynczym wierszu → log na poziomie `debug`, przebieg leci dalej

Żaden z tych przypadków nie może przerwać całego przebiegu ani wywrócić schedulera.

## 8. Konfiguracja

| Zmienna | Domyślnie | Rola |
|---|---|---|
| `ARGUS_CONGRESS_MIN_FILERS` | `3` | ilu różnych filerów musi tknąć ticker, by wszedł do uniwersum |
| `ARGUS_CONGRESS_BIG_TRADE` | `50000` | kwota, która sama wciąga ticker do uniwersum |
| `ARGUS_CONGRESS_FEED_URL` | URL z sekcji 3 | podmiana źródła bez rebuildu, gdy feed umrze |

Interwał joba: 1440 min (feed aktualizowany dziennie).

## 9. Pierwszy przebieg — backfill

Feed zawiera ~60 dni historii, więc pierwszy przebieg utworzy ~481 claimów z `entry_ts` w przeszłości, na ~93 aktywach. Evaluator rozliczy horyzont 30d natychmiast dla tych claimów, które są starsze niż 30 dni.

**Koszt:** ~480 wywołań yfinance o cenę historyczną przy pierwszym uruchomieniu (plus rozliczenia w evaluatorze), potem ~8 dziennie. To rząd wielkości więcej niż w v1 i jedyne miejsce, gdzie v2 jest droższe. Nie wymaga throttlingu, ale plan implementacji powinien przewidzieć uruchomienie backfillu **poza godzinami szczytu** i sprawdzenie logów pod kątem odrzuceń ze strony yfinance przed uznaniem deploya za udany.

Backfill jest pożądany: scoring źródeł kongresowych startuje z realnymi metrykami zamiast od zera.

## 10. Testy

Wszystkie offline, na zamrożonej próbce — bez sieci (testy Argusa lecą w kontenerze, sieć laptopa ma MITM proxy).

1. `Purchase` → `bull`; `Sale (Full)` i `Sale (Partial)` → `bear`
2. filtr odrzuca: `branch=executive`, pusty ticker, `asset_type=Stock Option`, `Exchange`
3. **filtr uniwersum**: ticker z 2 filerami i bez dużej transakcji nie tworzy claimów; ten sam ticker po dodaniu trzeciego filera — tworzy
4. **filtr uniwersum, druga ścieżka**: ticker z jednym filerem, ale transakcją ≥$50k, wchodzi do uniwersum
5. **`entry_ts == filing_date`, nie `transaction_date`** — test wprost broniący przed regresją look-ahead
6. **`HORIZONS_BY_METHOD["congress"] == {"30d"}`** — test broniący przed powrotem do fallbacku wszystkich horyzontów
7. dwukrotne uruchomienie na tej samej próbce → zero nowych claimów
8. ticker bez ceny z yfinance → brak wpisu w `assets` i brak claimu
9. drabinka confidence dla każdej z 8 etykiet z sekcji 6
10. `Source` powstaje raz per `filer_id`, przy wielu transakcjach tego samego polityka

## 11. Poza zakresem

- **widok „net aktywności per filer"** — odpowiednik śledzenia tradera; osobny increment po zebraniu scoringu (decyzja użytkownika)
- alerty Telegram (odłożone do czasu zebrania danych o wolumenie i hit-rate)
- horyzont 90d (patrz sekcja 12)
- transakcje opcyjne (feed nie ma danych do ustalenia kierunku)
- branża wykonawcza (`branch=executive`) — inny reżim ujawnień, osobny increment jeśli w ogóle
- historia głębsza niż okno feedu (~60 dni)
- zmiany w API i froncie
- przycinanie uniwersum aktywów (patrz sekcja 12)

## 12. Znane ryzyka

**30d może być za krótkim horyzontem.** Teza „kongresmen miał przewagę informacyjną" rozgrywa się raczej miesiącami niż tygodniami. Argus nie ma horyzontu 90d, a jego dodanie rusza słownik `HORIZONS` globalnie i dotyka wszystkich metod oraz progów w `THRESHOLDS`. Start na 30d jest świadomym kompromisem na rzecz zerowego ryzyka regresji; decyzję o 90d warto podjąć po zobaczeniu pierwszych rozkładów zwrotów.

**Pelosi jest słabym obiektem nauki.** ~24 claimy rocznie — próg oceny (5 claimów) przekroczy po ~2 miesiącach, ale jej score długo pozostanie statystycznie cienki, a przedziały ufności szerokie. Handluje rzadko i w nazwach, których nie tyka nikt inny (BE ma ją jako jedynego filera). Jeśli oczekiwaniem jest szybka odpowiedź „czy warto kopiować Pelosi", ten system jej nie da — da natomiast rzetelną odpowiedź o filerach aktywnych, na których jest 10–20× więcej danych.

**„Portfel" jest nieodtwarzalny z tych danych.** PTR-y raportują transakcje, nie stany posiadania, a feed obejmuje 60 dni. Możliwy jest wyłącznie widok net aktywności w oknie — nie skład portfela. Ma to znaczenie dla przyszłego incrementu „followowanie" i dla oczekiwań wobec dashboardu.

**Uniwersum aktywów tylko rośnie.** Ticker raz dodany zostaje `scorable=True` na zawsze. Przy ~93 aktywach na start i napływie nowych co okno, po roku może to być kilkaset pozycji w overview — z których część dawno wypadła z zainteresowania Kongresu. Przycinanie jest poza zakresem; kandydat na osobny, mały increment porządkowy.

**`external_id` oparty na `id` z feedu.** Dla Izby ma postać `house_<docid>_g<indeks>` — indeks pozycji w dokumencie. Gdyby upstream przeparsował dokument i zmienił kolejność wierszy, indeksy się przesuną i powstaną zduplikowane claimy. Świadomie wybrano prostotę nad obroną przed scenariuszem spekulatywnym. Alternatywa, gdyby problem wystąpił: hash treści (`filer_id + ticker + transaction_date + transaction_type + amount_range_low`), jak w `insider.py`.

**Feed jest projektem społecznościowym, nie usługą z SLA.** Jeśli repozytorium przestanie być aktualizowane, kolektor po cichu przestanie produkować claimy. `ARGUS_CONGRESS_FEED_URL` pozwala podmienić źródło bez rebuildu, ale samo wykrycie zastoju wymagałoby dodatkowego czeku — kandydat dla Guardiana, poza zakresem tego incrementu.

**Okno kroczące.** Transakcje spoza uniwersum nie są nigdzie zapisywane. Poszerzenie uniwersum w przyszłości zadziała tylko w przód — historii sprzed zmiany nie da się odzyskać. Świadomy koszt podejścia A (bez surowej tabeli).

## 13. Czym v2 różni się od v1

Ponowna analiza pod kątem samonauki i możliwości śledzenia traderów ujawniła dwie wady unieważniające v1:

1. **Pętla nauki się nie domykała.** Próg $50k na claimach dawał medianę 1 claimu na filera, przy progu oceny wynoszącym 5. Poprawka: rozdzielenie filtra uniwersum od filtra claimów (sekcja 4). Zmiana: 57 → 481 claimów na okno, 1 → 20 filerów zdolnych uzyskać ocenę.
2. **Spec przywracał błąd, który kod już naprawił.** Brak wpisu w `HORIZONS_BY_METHOD` oznaczał fallback na wszystkie horyzonty, a przy dacie bez składowej czasu horyzont 1h zwracałby zwrot 0 dla każdego claimu — systematyczne zaniżanie hit-rate. Poprawka: `"congress": {"30d"}` (sekcja 6).

Dodatkowo doprecyzowano, czego ten increment **nie** dostarcza w zakresie „followowania": odtworzenie portfela jest z tych danych niemożliwe, a widok net aktywności per filer został świadomie odłożony do osobnego incrementu.

## 14. Blokada: wyniki niezależnej recenzji (2026-08-29)

Recenzja pod kątem „czy pętla samonauki produkuje wiedzę, czy tylko wygląda, jakby produkowała". Wszystkie poniższe zweryfikowane bezpośrednio w kodzie i arytmetyce, nie przyjęte na słowo.

### 14.1 Blokery w rdzeniu Argusa (poza tym incrementem)

**B1. Scoring jest odwrócony dla claimów o bazowym hit-rate poniżej 0.5.**
`scorer.py:74` liczy `decayed = (wh_sum + a) / (w_sum + a + b)`. Podstawiając `wh_sum ≈ p·w_sum`, pochodna po sumarycznej wadze `w` ma znak `(4p − 2)` przy priorze Beta(2,2). Rośnie **wyłącznie** gdy `p > 0.5`. Przy progu `THRESHOLDS["30d"] = 0.08` na pojedynczej akcji bazowy hit-rate to ~0.2–0.3, więc:

| suma wag `w` | `decayed` przy p=0.25 | ocena |
|---|---|---|
| 0.08 (mediana filera) | 0.495 | C |
| 1.00 | 0.450 | C/D |
| 2.43 (najaktywniejszy) | 0.406 | D |

`/api/sources` sortuje `decayed_score DESC`, więc ranking uszereguje źródła **odwrotnie według ilości danych**. Ocena S (0.70) jest przy p poniżej 0.5 matematycznie nieosiągalna.

**B2. `tau_days=14` jest niespójne z horyzontem 30d.**
`age` liczony od `entry_ts` (`scorer.py:55`), a outcome dla `congress` powstaje najwcześniej 30 dni później. Waga w chwili rozliczenia: `exp(−30/14) = 0.117` — i to jest maksimum, dalej tylko spada. Efektywna liczba obserwacji z całego 60-dniowego backfillu (481 claimów): **13.6, rozłożone na 51 źródeł**. Dowód z sekcji 4, że 20 filerów przekroczy `min_claims=5`, dotyczy `n_claims`; o ocenie decyduje `decayed_score`. Dowiedziono nie tej statystyki.

**B3. Brak benchmarku — `hit_rate` mierzy betę rynkową.**
`evaluator.py` nie odnosi się nigdzie do zwrotu rynku ani sektora; `_hit` porównuje zwrot absolutny do stałej. Bazowy hit-rate zmienia się ~3× między hossą a bessą przy zerowej zmianie umiejętności. Ponieważ kongresmeni kupują głównie mega-capy, w hossie ranking uszereguje ich według udziału `Purchase` w claimach, w bessie — według udziału `Sale`. Do tego `macro_prior` (`scorer.py:65-66`) przesuwa prior o ±0.1, czyli więcej niż cały realny rozrzut z B1, i robi to w tę samą stronę co bias progowy — ten sam czynnik policzony dwa razy.

**B4. Bull i bear scorowane wspólnie.** `SourceScore` ma klucz `(source, horizon)` bez kierunku. Filer, który dużo sprzedaje, w rynku rosnącym dostaje niski wynik niezależnie od umiejętności. Sekcja 6 twierdzi, że „scoring i tak zweryfikuje, czy sprzedaże cokolwiek przewidują" — nie zweryfikuje, bo nie ma osobnego wyniku dla kupna i sprzedaży.

**Zakres B1–B4:** defekt dotyczy całego Argusa, nie tylko kolektora kongresowego. `insider` (horyzont `30d`) i `edgar` mają go **już dziś**, tylko na 7 tickerach, więc pozostał niezauważony.

**Proponowany kierunek naprawy** (do rozpisania w osobnym specu): prior ustawiany na **bazowy hit-rate kohorty dla pary (metoda, horyzont)**, przeliczany przy każdym scoringu, plus `tau` zależne od horyzontu, plus progi ocen liczone względem priora. Wtedy `decayed_score` z definicji znaczy „lepszy niż inni na tym samym typie claimu w tym samym reżimie rynkowym", co usuwa B1, B3 i B4 jednym ruchem, bez migracji i bez zewnętrznego benchmarku. Ryzyko przepisania historii jest zerowe: `recompute_scores` i tak kasuje i przelicza wszystkie wyniki od zera (`scorer.py:58-59`).

### 14.2 Poprawki do wniesienia w tym incremencie (gdy zostanie odblokowany)

**P1. `confidence` nie wpływa na scoring.** Nie występuje ani razu w `scorer.py` i `evaluator.py`. Ośmiostopniowa drabinka z sekcji 6 i test nr 9 z sekcji 10 są dekoracją — test przechodzi na zielono, nie weryfikując niczego. Do czasu naprawy rdzenia: zastąpić drabinkę stałą i usunąć test 9, albo świadomie zostawić z adnotacją. Osobna wada koncepcyjna: przedział kwotowy z PTR jest miarą **majątku**, nie przekonania.

**P2. „Bez zmian w API i froncie" jest nieprawdą.** `web/index.html:18` to selektor z opcjami 1h, 24h, 7d — **bez 30d**. Źródła `congress` miałyby wiersze `SourceScore` wyłącznie na 30d, więc nie pojawiłyby się w rankingu w żadnym stanie UI. Wymagana zmiana we froncie.

**P3. „Zerowe ryzyko regresji" jest nieprawdą.** `_edgar_job` (`main.py:126-128`) i `_llm_batch_job` (`main.py:34`) selekcjonują **wszystkie** aktywa `kind="stock", scorable=True`. 93 nowe aktywa wchodzą do nich automatycznie: EDGAR rośnie z 7 do ~100 tickerów co 6h (i utworzy claimy `method="insider"` dla 93 spółek, zanieczyszczając metrykę istniejącej metody), a grounding gate LLM dostaje uniwersum 21 → ~114 tickerów. Wymagane zawężenie białą listą albo osobny `kind`.

**P4. Kolizja klucza `assets.symbol`.** `symbol` jest globalnym kluczem głównym bez rozróżnienia po `kind`. Watchlista ma `XAI` jako **crypto** (`binance_symbol: XAIUSDT`), a `XAI` jest też realnym tickerem NYSE. Get-or-create bez sprawdzenia `kind` podpiąłby claim kongresowy pod aktywo krypto i wyceniał go z Binance — cicha korupcja danych. Klasa kolizji obejmuje też `DOT`, `RUNE`, `ONDO`, `JUP`. Wymagane: porównanie `kind` przy get-or-create + test.

**P5. Claimy nie są niezależnymi obserwacjami.** Filtr uniwersum z definicji selekcjonuje tickery kupowane przez wielu filerów w tym samym tygodniu, a jeden PTR obejmuje zwykle kilkanaście pozycji z tą samą `filing_date`. Przyrost 57 → 481 claimów jest w dużej części przyrostem skorelowanych duplikatów. Tania poprawka: deduplikacja na kluczu `(filer_id, ticker, filing_date, direction)` — jeden claim na filera-ticker-dzień zamiast jednego na wiersz.

**P6. `owner` jest ignorowany.** Transakcje z `owner=Spouse` bywają realizowane przez niezależnie zarządzany rachunek — przypisanie ich do źródła kongresmena mierzy jego brokera, nie jego. Wymagane: osobny handle albo pominięcie. Przy okazji `days_to_file` i `is_late` (potencjalnie najsilniejsze zmienne kontrolne) warto zapisywać w `ClaimAudit.parsed_claim` — kosztuje zero.

**P7. Kotwica dryfuje.** `_yf_historical` (`prices.py:26-30`) bierze pierwszy close **w dniu lub po dniu** `filing_date`, ale evaluator liczy horyzont od `entry_ts` = `filing_date`. Dla ujawnień w piątek lub sobotę realny horyzont to 28 dni, nie 30. Poprawka: zapisywać jako `entry_ts` faktyczną datę użytego bara.

**P8. Koszt evaluatora pominięty w sekcji 9.** `evaluate_due_claims` ładuje wszystkie claimy o statusie innym niż `closed` co 60 min. Przy ~480 otwartych claimach w oknie 30d to odpytywanie yfinance rzędu backfillu, powtarzane **24×/dobę**, a nie jednorazowo.

### 14.3 Co recenzja uznała za poprawne

Sam kolektor: filtry wejściowe, mapowanie kierunku, idempotencja przez `external_id`, kotwica w `filing_date` zamiast `transaction_date`, wpis w `HORIZONS_BY_METHOD`, oraz odłożenie hasha treści (`insider.py:73-75` jest gotowy do reużycia, gdyby problem z indeksem wystąpił). Testy 1–8 i 10 pokrywają mechanikę kolektora poprawnie — nie dotykają natomiast niczego, co decyduje o wartości rankingu.
