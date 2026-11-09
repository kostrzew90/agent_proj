# Argus — Increment A: kalibracja scoringu

**Data:** 2026-08-29
**Status:** design zaakceptowany, plan implementacji do napisania. Kodu nie zaczęto.
**Warunek wstępny dla:** `2026-08-29-argus-congress-trades-design.md` (zablokowany do czasu wdrożenia tego incrementu — patrz jego sekcja 14)

## 1. Problem

`decayed_score` w `scorer.py` nie mierzy tego, co ma mierzyć. Trzy niezależne defekty, wszystkie zweryfikowane w kodzie i arytmetyce 2026-08-29:

**D1 — scoring odwrócony dla claimów o bazowym hit-rate poniżej 0.5.**
`scorer.py:74`: `decayed = (wh_sum + a) / (w_sum + a + b)` przy priorze Beta(2,2). Podstawiając `wh_sum ≈ p·w_sum`, pochodna po sumarycznej wadze `w`:

```
d(decayed)/dw = (4p − 2) / (w + 4)²
```

Rośnie **wyłącznie** gdy `p > 0.5`. Dla progu `THRESHOLDS["30d"] = 0.08` na pojedynczej akcji bazowy hit-rate to ~0.2–0.3, więc:

| suma wag `w` | `decayed` przy p=0.25 | ocena |
|---|---|---|
| 0.08 | 0.495 | C |
| 1.00 | 0.450 | C/D |
| 2.43 | 0.406 | D |

`/api/sources` sortuje `decayed_score DESC`, więc ranking szereguje źródła **odwrotnie według ilości danych**. Ocena S (0.70) jest przy `p < 0.5` matematycznie nieosiągalna.

**D2 — `tau_days=14` niespójne z długimi horyzontami.**
`age` liczony od `entry_ts` (`scorer.py:55`), a outcome dla horyzontu 30d powstaje najwcześniej 30 dni później. Waga w chwili rozliczenia: `exp(−30/14) = 0.117` — i to jest maksimum, dalej tylko spada. Claim wchodzi do scoringu praktycznie martwy.

**D3 — brak benchmarku: `hit_rate` mierzy betę rynkową.**
`evaluator.py` porównuje zwrot absolutny do stałego progu, bez odniesienia do rynku. Bazowy hit-rate zmienia się ~3× między hossą a bessą przy zerowej zmianie umiejętności. Dodatkowo `macro_prior` (`scorer.py:65-66`) przesuwa prior o ±0.1 w tę samą stronę co bias progowy — ten sam czynnik policzony dwa razy.

**D4 — bull i bear scorowane wspólnie.** `SourceScore` ma klucz `(source, horizon)` bez kierunku. Źródło, które dużo sprzedaje, w rynku rosnącym dostaje niski wynik niezależnie od umiejętności.

**Zasięg:** defekt dotyczy całego Argusa. `insider` (horyzont `30d`) i `edgar` mają go już dziś, tylko na 7 tickerach, więc pozostał niezauważony. Ujawnił się przy projektowaniu kolektora kongresowego, który pomnożyłby go przez 51 źródeł.

## 2. Kryterium sukcesu

Weryfikowalne testem, nie opinią:

> Dla syntetycznego źródła o prawdziwym hit-rate `p` i kohorty o bazowym hit-rate `p_c`, `decayed_score` musi **rosnąć monotonicznie** z liczbą obserwacji gdy `p > p_c` i **maleć** gdy `p < p_c` — dla dowolnego `p_c`, nie tylko 0.5.

Dziś ten test przechodzi wyłącznie dla `p_c = 0.5`.

## 3. Decyzje podjęte przez użytkownika

| Decyzja | Wybór |
|---|---|
| Zakres kalibracji | **Wszystkie metody** (rss, reddit, news, llm, position, insider, edgar, przyszłe congress) |
| Traktowanie D4 | **Osobne wyniki bull i bear**, z migracją schematu |
| Benchmark SPY (podejście B) | Odrzucone — kohorta załatwia reżim rynkowy bez zewnętrznego szeregu |

Uzasadnienie zakresu: `recompute_scores` kasuje i przelicza wszystkie wyniki od zera przy każdym przebiegu (`scorer.py:58-59`), więc nie ma historii do stracenia. Przetasowanie rankingu RSS/reddit jest jednorazowym kosztem spójnej semantyki.

## 4. Rozwiązanie

### 4.1 Prior z kohorty (naprawia D1 i D3)

Dla każdej trójki `(metoda, horyzont, kierunek)` liczymy bazowy hit-rate `p_c` ze wszystkich outcome'ów w tej grupie. Prior Beta ustawiamy jako:

```
a = p_c · k        b = (1 − p_c) · k        k = 4
```

Wtedy, podstawiając `wh ≈ p·w`:

```
d(decayed)/dw = k·(p − p_c) / (w + k)²
```

Znak pochodnej to **`(p − p_c)`** zamiast `(4p − 2)`. Więcej danych podnosi wynik wtedy i tylko wtedy, gdy źródło bije kohortę — niezależnie od tego, czy bazowy hit-rate wynosi 0.25 czy 0.55.

To rozwiązuje także D3: kohorta przesuwa się razem z reżimem rynkowym, więc hossa podnosi wszystkich i nie wyróżnia nikogo. Zewnętrzny benchmark przestaje być potrzebny do rankingu (pozostaje przydatny do raportowania — poza zakresem).

### 4.2 Kohorta z pominięciem samego źródła (leave-one-out)

Źródło dominujące w swojej metodzie porównywałoby się do siebie i nie mogłoby kohorty pobić. Przykład z danych kongresowych: jeden filer odpowiada za ~⅕ claimów metody. Kohorta dla źródła `s` liczona jako `(hits_grupy − hits_s) / (n_grupy − n_s)`.

### 4.3 Ściąganie do neutralnego przy małej próbie (cold start)

```
p_c = (hits + 10) / (n + 20)
```

Metoda z tysiącem obserwacji dostaje prior z danych; metoda z dwudziestoma — bliski 0.5. Bez tego nowa metoda dostaje prior wyznaczony przez kilka przypadkowych trafień.

### 4.4 `tau` zależne od horyzontu (naprawia D2)

```
TAU_BY_HORIZON = {"1h": 14, "24h": 14, "7d": 30, "30d": 120}
```

Reguła doboru: waga w chwili rozliczenia ma wynosić co najmniej 0.75, czyli `tau ≥ 4×` długość horyzontu. Kontrola: `exp(−30/120) = 0.78`, `exp(−7/30) = 0.79`, `exp(−1/14) = 0.93`. Dziś dla horyzontu 30d wynosi 0.117.

### 4.5 Progi ocen względem kohorty

`argus_grade` przestaje operować na bezwzględnych progach (S≥0.70, A≥0.60, B≥0.52, C≥0.45) i liczy ocenę na **nadwyżce** `decayed − p_c`. Źródło bez danych siedzi na kohorcie, więc dostaje C; żeby ruszyć w górę, musi mieć jednocześnie przewagę i obserwacje — bo nadwyżka jest z definicji ściągnięta czynnikiem `w/(w+k)`.

`min_claims = 5` zostaje jako druga, niezależna bariera.

Konkretne progi nadwyżki do ustalenia w planie implementacji na podstawie rozkładu z żywych danych; punkt wyjścia: S ≥ +0.15, A ≥ +0.08, B ≥ +0.03, C ≥ −0.03, D poniżej.

### 4.6 Rozdział bull/bear (naprawia D4)

`direction` wchodzi do klucza `SourceAssetScore` i `SourceScore`. Obok wierszy `bull` i `bear` liczony jest trzeci, `all` — domyślny widok rankingu.

**Migracja jest darmowa.** Obie tabele są kasowane i przeliczane od zera przy każdym `recompute_scores`, więc wystarczy je dropnąć i pozwolić `Base.metadata.create_all` odtworzyć ze zmienionym `UniqueConstraint`. Zero utraty danych — to dane pochodne.

### 4.7 Usunięcie `macro_prior`

Przy priorze z kohorty korekta makro liczy ten sam czynnik drugi raz. Kolektor FRED i tabela `macro_data` zostają nietknięte (przydatne do raportowania i przyszłych analiz); przestajemy jedynie przesuwać nimi prior w `scorer.py:65-66`.

**To świadome usunięcie wcześniej dodanej funkcji, nie przeoczenie.** Odnotowane wprost, bo `macro_prior` był wprowadzony celowo w ramach kolektora FRED.

### 4.8 API i front

- `/api/sources` dostaje parametr `direction` (domyślnie `all`)
- selektor horyzontu w `web/index.html:18` dostaje opcję `30d` (dziś ma tylko 1h/24h/7d, przez co źródła o wynikach wyłącznie na 30d są niewidoczne w rankingu)

## 5. Pliki

**Zmieniane:**

- `argus/scorer.py` — rdzeń zmiany: kohorta, leave-one-out, shrinkage, tau per horyzont, progi względne, usunięcie macro_prior, rozdział po kierunku
- `argus/models.py` — kolumna `direction` w `SourceAssetScore` i `SourceScore` + zmiana `UniqueConstraint`
- `argus/api.py` — parametr `direction` w `/api/sources`
- `argus/web/index.html`, `argus/web/app.js` — opcja `30d`, filtr kierunku
- `tests/test_scorer.py` — testy z sekcji 6

**Bez zmian:** kolektory, `evaluator.py`, `prices.py`, `db-init`.

## 6. Testy

1. **Test rozstrzygający (kryterium z sekcji 2):** syntetyczne źródło o zadanym `p` w kohorcie o zadanym `p_c`; `decayed_score` rośnie monotonicznie z liczbą obserwacji gdy `p > p_c`, maleje gdy `p < p_c`. Sprawdzone dla `p_c` = 0.25, 0.5, 0.7.
2. Źródło o `p = p_c` pozostaje na poziomie kohorty niezależnie od liczby obserwacji.
3. Leave-one-out: źródło stanowiące większość kohorty potrafi ją pobić, gdy jego `p` przewyższa resztę grupy.
4. Cold start: grupa z 5 obserwacjami ma `p_c` bliskie 0.5 mimo skrajnego surowego hit-rate.
5. `TAU_BY_HORIZON` — waga claimu w chwili rozliczenia ≥0.75 dla każdego horyzontu.
6. Rozdział kierunku: claimy bull i bear tego samego źródła trafiają do osobnych wierszy; wiersz `all` agreguje oba.
7. Ocena względna: źródło na poziomie kohorty dostaje C przy dowolnym `p_c`.
8. Brak regresji: istniejące testy `test_scorer.py` przechodzą albo zostają świadomie zaktualizowane wraz z uzasadnieniem zmiany oczekiwań.

## 7. Poza zakresem

- benchmark SPY / `ret_excess` (podejście B — odrzucone, kohorta wystarcza do rankingu)
- zmiany w `evaluator.py` i progach `THRESHOLDS`
- przedziały ufności w modelu i UI (`SourceScore` nie przechowuje wariancji ani `n_effective`) — realna luka, osobny increment
- deduplikacja skorelowanych claimów — należy do kolektorów, nie do scorera
- porównywalność ocen **między** metodami: po tej zmianie ocena znaczy „lepszy niż kohorta własnej metody", co czyni litery porównywalnymi, ale `decayed_score` nadal nie jest — `/api/sources` sortujący jedną listą po `decayed_score` pozostaje wadliwy i wymaga sortowania po nadwyżce; do rozstrzygnięcia w planie

## 8. Znane ryzyka

**Kohorta jest tak dobra, jak jej liczność.** Metoda z jednym aktywnym źródłem nie ma sensownej kohorty — `p_c` degeneruje się do własnego wyniku tego źródła, a leave-one-out zwraca pustą grupę. Wymagany fallback: przy `n_grupy − n_s < 20` używamy `p_c = 0.5`. Dotyczy dziś metody `derived` (Whale Consensus, jedno źródło).

**Progi nadwyżki są zgadywane.** Wartości z sekcji 4.5 to punkt wyjścia, nie pomiar. Powinny zostać skalibrowane na rozkładzie z żywych danych przed uznaniem incrementu za zamknięty — inaczej wymieniamy jeden arbitralny zestaw progów na inny.

**Przetasowanie istniejącego rankingu.** Po wdrożeniu oceny wszystkich źródeł RSS/reddit/news zmienią się jednorazowo. To zamierzone, ale warto zapisać stan sprzed zmiany, żeby móc porównać i wychwycić niespodzianki.

**Ten increment nie czyni rankingu istotnym statystycznie.** Naprawia znak i wagę, nie moc. Odróżnienie hit-rate 0.60 od 0.50 przy dwustronnym teście i mocy 0.80 wymaga ~194 obserwacji; przy realistycznej przewadze +3pp — rzędu 2000. `min_claims = 5` pozostaje progiem widoczności, nie progiem istotności. Przedziały ufności są poza zakresem (sekcja 7), więc UI nadal będzie pokazywać literę bez informacji o niepewności.
