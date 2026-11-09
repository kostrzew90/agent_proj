# Argus — Liquidation Cascade Signals (Increment 9)

**Data:** 2026-06-24
**Status:** draft — czeka na review użytkownika

## Kontekst

Increment 5 (05.06) wprowadził tabelę `liquidations` jako **market-context tylko do wglądu** — świadomie wyłączoną ze scoringu wiarygodności źródeł i z Signal Notifiera. 18.06 listener przepisano z Binance WS na REST polling Hyperliquid `userFills`. 23.06 wykryto i naprawiono bug: kod sprawdzał nieistniejące pole `liquidationId` zamiast realnego pola `liquidation` (obiekt) — wszystkie likwidacje były od 18.06 silently dropowane. Po fixie: **417 historycznych rekordów** (BTC, ETH; listopad 2025 – czerwiec 2026).

Cel tego incrementu: wykorzystać te dane **do zarobku** — wykryć, czy kaskady likwidacji (duży notional zlikwidowany w krótkim oknie, głównie jedna strona) mają realną wartość predykcyjną dla monitorowanych aktywów, i jeśli tak — zintegrować to z Signal Notifierem (Telegram).

## Problem: dwie sprzeczne hipotezy tradingowe

Kaskady likwidacji interpretuje się dwojako:
- **Kontrarian** ("long squeeze"): masowa likwidacja longów = kapitulacja = możliwe dno, cena odwraca się w górę.
- **Kontynuacja**: likwidacje przyspieszają już trwający trend, cena kontynuuje w stronę likwidacji.

Argus nie ma a priori powodu wierzyć w jedną z nich — zgodnie z fundamentalną zasadą projektu ("samonauka = wiarygodność, NIE trafność tez założona z góry"), **decyzję podejmują dane**, nie intuicja.

## Decyzja architektoniczna: reuse istniejącego pipeline'u, zero nowych tabel

Kaskada likwidacji staje się **claimem od syntetycznego źródła** (`Source(kind="derived")`) — analogicznie do już istniejącego "Whale Consensus" z Incrementu 3. Dzięki temu cały mechanizm samonauki działa bez zmian:
- Outcome Evaluator (1h/24h/7d vs cena) — już działa dla każdego claima niezależnie od source.kind.
- Source Scorer (Bayesian decay, hit_rate, n_claims, decayed_score) — już działa.
- `passes_gate()` / `effective_score()` w `signals.py` — już działa.
- Dashboard (`/api/sources`) — już pokazuje wszystkie source'y ze score'ami.

**Co to NIE zmienia:** istniejące tiery `check_whale_signals` i `check_confluence_signals`, scoring innych źródeł, dashboard UI, schemat `liquidations` table.

## Korekta po code review (2026-06-24)

Zewnętrzny review (8.5/10, główne ryzyko: "system może nauczyć się przypadkowego wzorca z 417 rekordów i uznać go za przewagę") wniósł 9 punktów. Przyjęte do designu poniżej (8/9 — punkt o Open Interest odłożony, brak kolektora OI):

1. **`min_events_required` w backteście** (próg 20-30) — konfiguracja z mniejszą liczbą wykrytych kaskad zwraca `"insufficient_data"`, nie wymusza wyboru `direction_rule`.
2. **Confidence proporcjonalna do wielkości kaskady**, nie sztywne 0.5 — `cascade_strength = total_notional / rolling_30d_p95_notional`, `confidence = clamp(0.3 + cascade_strength * 0.4, 0.3, 0.9)`.
3. **Cooldown/merge dla nakładających się okien** — okno kroczące na ciągłym squeeze potrafi wygenerować serię niemal identycznych kaskad z tego samego ruchu rynku. Merge gdy nowe okno nakłada się >50% z poprzednią kaskadą tego samego `(asset, side)`, albo `cooldown_per_asset_side = 60min` po zamknięciu kaskady.
4. **`price_change_window` w `CascadeEvent`** (zmiana ceny w ostatnich 15 min przed kaskadą) — backtest testuje też hipotezę "likwidacje + momentum" osobno od "same likwidacje", bo np. 20M short_liq przy price+8% to inny sygnał niż 20M short_liq przy price+0.5%.
5. **`cascade_intensity = total_notional / duration_minutes`** jako dodatkowy wymiar sweep w backteście, niezależny od samego `total_notional` — 50M w 2 min ≠ 50M w 60 min.
6. **Gating per-asset BEZ rozdzielania source'ów** (korekta własna, nie z review — patrz niżej) — review proponował `liq-cascade-btc`/`liq-cascade-eth` jako osobne source'y, żeby uniknąć wymieszania BTC/ETH przez Bayesian scorer. Sprawdziłem: Argus **już ma** `SourceAssetScore` (`source_id, asset, horizon` — `argus/models.py:77`), generycznie wypełnianą przez `recompute_scores()` w `scorer.py` dla każdego claima niezależnie od source.kind. Problem jest gdzie indziej: `signals.py::_get_source_score()` gatuje na **globalnym** `SourceScore` (`source_id, horizon`, bez `asset`) — to dotyczy też dzisiejszych tierów whale/confluence, nie tylko kaskad (osobny, pre-existing gap, **poza scope** tego incrementu). Fix dla kaskad: `check_liquidation_signals` gatuje na `SourceAssetScore(source_id="liq-cascade", asset=X, horizon)` — jeden globalny source, per-asset rozróżnienie przez kolumnę `asset`, którą tabela już ma. Brak duplikacji source'ów przy dodawaniu kolejnych aktywów do watchlisty w przyszłości.
7. **Benchmark w raporcie backtestu** — nie tylko `contrarian 58% / continuation 47%`, ale też `random=50%` i `buy-and-hold return` dla okresu, żeby 55% hit-rate przy małym n nie wyglądał na przewagę, gdy nią nie jest.
8. **Fix look-ahead bias** — kaskada wykryta w oknie `10:00–10:30` nie może mieć `entry_price` z `10:00` (środek/początek okna, który backtest "widzi" tylko post-factum). `entry_ts` i `entry_price` dla claima/backtestu = **koniec okna** (`window_end`), bo to pierwszy moment, w którym sygnał realnie istnieje.

**Odłożone (poza scope tego incrementu):** Open Interest jako drugi wymiar (`Liquidation Cascade` vs `Liquidation + OI Flush` jako osobne source'y) — wymaga nowego kolektora danych z Hyperliquid, który nie istnieje. Kandydat na Increment 10, nie teraz.

## Komponenty do zbudowania

### 1. `argus/liquidations/cascade.py` (nowy plik)

```python
@dataclass
class CascadeEvent:
    asset: str
    side: str                    # long_liq | short_liq
    window_start: datetime
    window_end: datetime         # sygnał "istnieje" od tego momentu (look-ahead fix, patrz pkt 8)
    total_notional: float
    n_fills: float
    cascade_intensity: float     # total_notional / duration_minutes (pkt 5)
    price_change_window: float   # zmiana ceny w 15 min PRZED window_start (pkt 4, momentum)
```

```python
def detect_cascades(liquidations, window_minutes, min_notional, merge_overlap_pct=0.5) -> list[CascadeEvent]
```
Grupuje wiersze `liquidations` w kroczące okna per `(asset, side)`. Kaskada = suma `notional_usd` w oknie ≥ `min_notional`. **Merge nakładających się okien** (pkt 3): jeśli kolejne wykryte okno tego samego `(asset, side)` nakłada się >`merge_overlap_pct` z poprzednim, scala w jedną kaskadę (sumuje notional, rozszerza `window_end`) — zapobiega serii niemal identycznych claimów z jednego squeeze'u. Dolicza `price_change_window` (cena na początku okna vs cena 15 min wcześniej) i `cascade_intensity`.

```python
def emit_cascade_claims(session, cascades: list[CascadeEvent], direction_rule: dict[str, str], notional_p95: float) -> int
```
Dla każdej kaskady: dedup przez `ClaimAudit.raw_text == f"LIQ_CASCADE:{asset}:{side}:{window_start.isoformat()}"`. Jeśli nowa i `asset in direction_rule`: ustala `direction` (`"contrarian"` → long_liq⇒bull, short_liq⇒bear; `"continuation"` → odwrotnie), liczy **confidence proporcjonalną do wielkości** (pkt 2): `cascade_strength = total_notional / notional_p95`, `confidence = clamp(0.3 + cascade_strength * 0.4, 0.3, 0.9)`. `entry_price` = cena z `window_end` (**nie** `window_start` — look-ahead fix, pkt 8), `entry_ts = window_end`. Tworzy `Claim(source_id=<liq-cascade source>, method="rule", confidence=...)` + `ClaimAudit`. Jeśli `asset not in direction_rule` → pomija (świadomie, "za mało danych", nie zgadujemy).

Jeden syntetyczny source: `Source(kind="derived", handle="liq-cascade", display_name="Liquidation Cascade")`, insert-if-not-exists (wzorzec z `collectors/hyperliquid.py`). **Per-asset rozróżnienie przez `SourceAssetScore.asset`, nie przez osobne source'y** — patrz "Korekta po code review", pkt 6.

### 2. Scheduler job `_liq_cascade_job` (`argus/main.py`)

Co 30-60 min (do ustalenia po zobaczeniu jak często dane się zmieniają — `liq-listener` poluje co 120s, więc 30 min daje >10 nowych odczytów do analizy). Wzorzec identyczny jak istniejące joby: `try/except` + log, nie crashuje schedulera przy błędzie. Czyta `liquidations` z ostatnich N godzin (lookback = window_minutes + bufor), wywołuje `detect_cascades` + `emit_cascade_claims`.

### 3. `signals.py::check_liquidation_signals(session)` (nowy tier)

Analogiczny do `check_whale_signals`, ale gatuje na **`SourceAssetScore`** (nie globalnym `SourceScore` — korekta z pkt 6): szuka świeżej kaskady (claim od source `liq-cascade`, `entry_ts` w ostatnich `_WHALE_LOOKBACK_MINUTES`), pobiera `SourceAssetScore(source_id, asset=claim.asset, horizon="24h")`, sprawdza `passes_gate(decayed_score, n_claims)` na TYM rekordzie (per-asset, nie zmieszany BTC+ETH). Jeśli przechodzi: tworzy `SignalResult(tier="liq_cascade", ...)`, reużywając `compute_sizing`. Dodany do `send_signals()` razem z whale+confluence.

`format_signal_message`: dodanie wariantu emoji/tier_str dla `tier == "liq_cascade"` (np. 🌊 LIKWIDACJA · BULLISH BTC/USDT).

### 4. `scripts/backtest_liq_cascades.py` (one-off, NIE wdrażany do crona/repo jako trwała część app)

Cel: zdecydować `direction_rule` PRZED puszczeniem mechanizmu live, używając 417 już zebranych rekordów.

Sweep: `window_minutes ∈ {15, 30, 60}` × `min_notional` (kilka wartości z rozkładu realnych notionali) × `cascade_intensity` jako alternatywny próg (pkt 5) × z/bez filtra `price_change_window` (momentum, pkt 4). Dla każdej kombinacji: entry = cena na `window_end` (**nie** `window_start`, pkt 8 — look-ahead bias), porównanie z ceną +1h/+24h/+7d (reużywa `evaluator.py`/`prices` cache, fallback do historycznych Binance klines on-demand). Liczy hit-rate dla obu hipotez **per aktywo**.

**Próg minimalnej próby (pkt 1):** `min_events_required = 25`. Konfiguracja z mniejszą liczbą wykrytych kaskad zwraca `"insufficient_data"`, nie wymusza wyboru `direction_rule` — zapobiega uczeniu się szumu na n=5-11 (przykład z review).

**Raport z benchmarkiem (pkt 7):** każda konfiguracja raportuje `random=50%`, `buy_and_hold_return` dla okresu, oraz `contrarian_hit_rate` / `continuation_hit_rate` — 55% hit-rate przy n=15 ma inną wagę niż 55% przy n=200, raport musi to pokazać explicite, nie tylko surowy hit-rate.

**Decyzja `direction_rule`** zapada na podstawie tego raportu, TYLKO dla konfiguracji z n ≥ `min_events_required`. Jeśli BTC i ETH różnią się, `direction_rule` to dict per-symbol (wzorzec jak `_VOL_TIER_MAP`); jeśli któreś aktywo nie ma wystarczającej próby — nie ma wpisu w `direction_rule`, `emit_cascade_claims` pomija jego kaskady.

## Gating, sizing, ryzyko

Bez zmian — reuse `passes_gate` (decayed_score≥0.60, n_claims≥5), `effective_score`, `compute_sizing`, `_is_on_cooldown`. Source "liq-cascade" musi **samodzielnie zarobić** sobie na alert tak jak każdy inny source — żadnych specjalnych progów.

## Testowanie (TDD, wzorzec z `test_hl_liq_listener.py` / `test_signals.py`)

- `test_cascade.py`: `detect_cascades` — grupowanie w oknie, próg notional, granice okna (fill na granicy), brak fillów = brak kaskady, multi-asset/multi-side niezależność, **merge nakładających się okien tego samego (asset,side)** (pkt 3), poprawny `cascade_intensity` i `price_change_window`.
- `emit_cascade_claims` — dedup (drugie wywołanie z tym samym oknem nie tworzy duplikatu), poprawny `direction` per `direction_rule`, **`entry_price`/`entry_ts` = `window_end`, nigdy `window_start`** (test na look-ahead bias, pkt 8), **confidence skaluje się z `cascade_strength`** (mała kaskada → confidence bliżej 0.3, ekstremalna → bliżej 0.9, pkt 2), brak ceny → skip z logiem, `asset not in direction_rule` → skip.
- `test_signals.py`: nowy `check_liquidation_signals` — gate pass/fail **na `SourceAssetScore`, nie `SourceScore`** (test musi pokazać że dobry score na BTC + słaby na ETH dla tego samego source NIE blokuje/nie zawyża wzajemnie), cooldown, sizing.
- Backtest script: bez formalnych testów jednostkowych (one-off analysis tool), ale ręczna weryfikacja na małej znanej próbce przed pełnym przebiegiem — w tym explicit sprawdzenie, że `min_events_required` faktycznie blokuje wybór reguły przy małym n.

## Error handling

- Brak ceny w momencie kaskady → log warning + skip (jak istniejący `confluence` kod).
- `_liq_cascade_job` failure → log error, scheduler kontynuuje (wzorzec identyczny jak inne joby).
- Brak wpisu w `direction_rule` dla aktywa → cicho pomiń (to nie błąd, to świadoma decyzja "za mało danych").

## Out of scope (explicit)

- Nie zmieniamy `_ELIGIBLE_KINDS` w `check_confluence_signals` (obecnie wyklucza `kind="derived"` — to dotyczy też istniejącego Whale Consensus, osobny, niezależny gap, nie część tego incrementu).
- Nie dotykamy schematu tabeli `liquidations` ani istniejącego panelu dashboardu (czerwony/zielony, market-context).
- Nie wdrażamy automatycznego re-tuningu `window_minutes`/`min_notional` — wartości z backtestu są statyczne do następnego review.

## Otwarte pytania do potwierdzenia po backteście

1. Jaki `window_minutes` / `min_notional` faktycznie wykrywa sensowne kaskady w danych (nie wiadomo, dopóki nie zobaczymy rozkładu).
2. Czy BTC i ETH wymagają różnych reguł (`direction_rule` per-symbol) czy jednej wspólnej.
3. Częstotliwość `_liq_cascade_job` (30 vs 60 min) — do ustalenia empirycznie po zobaczeniu jak gęsto przychodzą nowe likwidacje na żywo (obecnie ~417 w ~7 miesięcy = rzadko, ale to dotyczy tylko śledzonych portfeli, nie całego rynku).
