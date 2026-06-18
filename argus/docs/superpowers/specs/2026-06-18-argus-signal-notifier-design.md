# Argus Signal Notifier — Design Spec

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Argus wysyła Telegramem alerty inwestycyjne z rekomendacją pozycji gdy wiarygodne źródła generują sygnał.

**Data:** 2026-06-18
**Status:** Zaakceptowany, zaktualizowany po recenzji Opus (2026-06-18).

---

## Kontekst

Argus od ~15 dni uczy się wiarygodności źródeł (hit_rate per source per horyzont). Zebrane dane (scorer rankings z 2026-06-18) pokazują realną hierarchię:

- **Najlepsze źródła:** r/SatoshiStreetBets (80% hit@24h, n=5), HL whale 0x9321 (75% hit@24h, n=4)
- **Słabe:** r/CryptoCurrency (26% hit@24h, n=66), Yahoo Finance (~17%)

Brakuje warstwy która **działa na tych naukach** — system dotąd zbiera i ocenia, ale nie powiadamia.

---

## Strategia sygnałów

### Horyzont inwestycyjny

- **Krypto:** short-term (24h) — szybkie wejście/wyjście
- **Akcje:** swing (7d) — kilkudniowe pozycje

### Scoring źródeł — effective_score

Surowy `decayed_score` jest korygowany przez liczbę ewaluowanych claimów:

```
effective_score = decayed_score × min(1.0, n_claims / 30)
```

Przykład: źródło A (score=0.75, n=8) → effective=0.75×0.27=**0.20**; źródło B (score=0.72, n=120) → effective=0.72×1.0=**0.72**. B jest wiarygodniejsze mimo niższego raw score.

`n_claims` = max po wszystkich horyzontach z `source_scores` dla danego źródła.

### Dwa tryby wyzwalania

**Tier 1 — Whale Alert (tylko krypto, natychmiastowy)**

Wyzwalacz: HL whale z `effective_score ≥ 0.55` otwiera lub zmienia pozycję (nowy wpis w `wallet_positions` z ostatnich 10 minut).

Alert wysyłany w ciągu 10 minut od wykrycia. Tier 1 nie wymaga confluence — whale move sam w sobie jest sygnałem.

**Tier 2 — Confluence Alert (krypto + akcje)**

Wyzwalacz: ≥ 2 źródła z **różnych kategorii** (`source.kind`) zgadzają się co do tego samego assetu i kierunku (bullish/bearish) w oknie **2 godzin**. Każde źródło musi mieć `effective_score ≥ 0.55`.

Siła confluence liczona probabilistycznie (nie średnia):
```
combined_strength = 1 − Π(1 − effective_score_i)
```
Przykład: dwa źródła 0.61+0.61 → combined=0.84. Dwa źródła 0.80+0.80 → combined=0.96.

Minimum `combined_strength ≥ 0.75` żeby sygnał przeszedł.

Różne `source.kind` = np. `reddit` + `hyperliquid`, `reddit` + `news`. Dwa źródła tego samego rodzaju nie tworzą confluence.

Alert wysyłany co 15 minut (job scan). **Maksymalnie top 3 sygnały per cykl** (ranking po `combined_strength`) — zapobiega spamowi gdy market rusza jednocześnie wiele assetów.

---

## Sizing recommendation

Formuła: `position% = risk% / stop_loss%`

Signal strength do sizingu = `combined_strength` (Tier 2) lub `effective_score` (Tier 1).

| Signal strength | Ryzyko na trade | Pozycja (przy stop 5%) | Pozycja (przy stop 3%) |
|---|---|---|---|
| 0.55 – 0.75 | 1% portfela | 20% portfela | 33% portfela |
| 0.75 – 0.90 | 2% portfela | 40% portfela | 67% portfela |
| 0.90+ | 3% portfela | 60% portfela | max 50% |

**Stop-loss według volatility tier (stały %, nie ATR):**

| Tier | Przykłady | Stop krypto | Stop akcje |
|---|---|---|---|
| Large cap | BTC, ETH | 5% | 3% |
| Mid cap | SOL, ADA, AVAX, większość akcji | 7% | 4% |
| Small cap | DOGE, SHIB, mniejsze alts | 10% | 5% |

Tier assignowany per asset w `config/assets.yaml` (pole `vol_tier: large|mid|small`). Default: `mid`.

Entry price: spot w momencie alertu; dla Tier 1 whale: cena otwarcia pozycji z `wallet_positions.entry_px`.

**Przykład:** Whale (effective_score=0.55) otwiera long BTC@$67,400 (large cap):
```
Signal strength: 0.55 → ryzyko 1%
Stop: $64,030 (-5%)
Pozycja: 20% portfela
```

---

## Format wiadomości Telegram

**Tier 1 — Whale:**
```
🐋 WHALE SIGNAL · BULLISH ETH/USDT

Whale: 0x9321...d75a
Effective score: 0.55 · 75% hit@24h · n=8
Pozycja: $2.1M long @ $3,420

Entry teraz: ~$3,445
Stop-loss: $3,273 (-5%, large cap)
Pozycja: 20% portfela (ryzyko 1%)
Horyzont: 24h
```

**Tier 2 — Confluence:**
```
⚡ CONFLUENCE · BULLISH BTC/USDT · strength 0.84

• r/SatoshiStreetBets · eff. 0.61 · 80%@24h
• HL whale 0x5078 · eff. 0.61 · 60%@24h
Zgodność: 2 źródła · okno 1h45m

Entry teraz: ~$67,400
Stop-loss: $64,030 (-5%, large cap)
Pozycja: 20% portfela (ryzyko 1%)
Horyzont: 24h
```

---

## Architektura

### Nowe pliki

**`argus/signals.py`**
- `effective_score(source_score: float, n_claims: int) -> float`
- `combined_strength(scores: list[float]) -> float` — probabilistyczna kombinacja
- `check_whale_signals(session) -> list[SignalResult]`
- `check_confluence_signals(session) -> list[SignalResult]`
- `compute_sizing(strength: float, vol_tier: str, asset_type: str) -> dict`
- `format_signal_message(signal: SignalResult) -> str`

**`argus/telegram.py`**
- `send_message(text: str) -> None` — POST do Telegram Bot API
- Reużywa `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` z `.env` (ten sam bot co Guardian)
- Błąd → log, nie retry (sygnał time-sensitive)

### Zmiany w istniejących plikach

**`argus/models.py`**

Nowa tabela `signal_log`:
```python
class SignalLog(Base):
    __tablename__ = "signal_log"
    id: int (PK)
    tier: str           # "whale" | "confluence"
    asset: str          # "BTC"
    direction: str      # "bullish" | "bearish"
    source_ids: str     # JSON list of source IDs
    signal_strength: float
    entry_price: float
    stop_price: float
    position_pct: float
    sent_at: datetime
```

Nowa tabela `signal_outcomes` (wypełniana przez ewaluator co 24h/7d):
```python
class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    id: int (PK)
    signal_id: int (FK signal_log.id)
    asset: str
    entry_price: float
    price_24h: float | None
    price_7d: float | None
    max_favorable_excursion: float | None  # max zysk po wejściu
    max_adverse_excursion: float | None    # max strata po wejściu
    hit_stop: bool | None                  # czy stop-loss uderzony
    outcome: str | None                    # "win" | "loss" | "open"
    evaluated_at: datetime | None
```

`signal_outcomes` to najważniejsza tabela projektu — po 2-3 miesiącach pozwoli mierzyć realną skuteczność alertów, nie tylko jakość źródeł.

**`argus/main.py`**
Trzy nowe jopy w schedulerze:
- `_whale_signal_job` — co 10 minut
- `_confluence_signal_job` — co 15 minut
- `_signal_outcomes_job` — co 6h (ewaluuje otwarte sygnały starsze niż 24h)

### Cooldown

- **2h per asset** — żaden asset nie generuje więcej niż 1 alertu na 2 godziny (niezależnie od tier)
- Sprawdzane przez `signal_log.sent_at` + `signal_log.asset`

### Flow danych

```
_whale_signal_job (co 10min)
  → wallet_positions WHERE created_at > now()-10min
  → JOIN source_scores, oblicz effective_score
  → FILTER: effective_score >= 0.55
  → cooldown check (signal_log, asset, 2h)
  → compute_sizing(effective_score, vol_tier, "crypto")
  → format + send_message()
  → INSERT signal_log (z entry_price, stop_price, position_pct)
  → INSERT signal_outcomes (outcome="open")

_confluence_signal_job (co 15min)
  → claims WHERE entry_ts > now()-2h
  → JOIN source_scores, oblicz effective_score per source
  → FILTER: effective_score >= 0.55
  → GROUP BY (asset, direction)
  → FILTER: >= 2 różne source.kind w grupie
  → combined_strength = 1 - Π(1 - eff_score_i)
  → FILTER: combined_strength >= 0.75
  → SORT BY combined_strength DESC, TAKE top 3
  → cooldown check per asset
  → compute_sizing(combined_strength, vol_tier, asset_type)
  → format + send_message()
  → INSERT signal_log + signal_outcomes

_signal_outcomes_job (co 6h)
  → signal_outcomes WHERE outcome="open" AND signal_log.sent_at < now()-24h
  → fetch current price (Binance/yfinance)
  → update price_24h, price_7d, hit_stop, outcome
  → log summary
```

---

## Out of scope

- Exit signals (kiedy wyjść z pozycji) — poza zakresem tego incrementu
- Auto-execution przez API giełdy — ręczne wykonanie przez usera
- Portfolio tracking (ile mam otwartych pozycji) — poza zakresem
- Push notifications inne niż Telegram
- ATR-based stop-loss — stały % wystarczy na tym etapie

---

## Progi kwalifikacyjne — podsumowanie

| Parametr | Wartość |
|---|---|
| Min effective_score (Tier 1 whale) | ≥ 0.55 |
| Min effective_score (Tier 2 każde źródło) | ≥ 0.55 |
| Confidence factor | min(1.0, n_claims/30) |
| Confluence: min źródeł | 2 z różnych `kind` |
| Confluence: combined_strength min | ≥ 0.75 |
| Confluence: okno czasowe | 2h |
| Confluence: max sygnałów per cykl | 3 (top by strength) |
| Cooldown per asset | 2h |
| Tier 1 scan interval | 10 min |
| Tier 2 scan interval | 15 min |
| Signal outcomes eval interval | 6h |

---

## Rozwiązane pytania (z recenzji Opus 2026-06-18)

1. **n_claims próg** — nie ma twardego progu; zamiast tego `effective_score = score × min(1.0, n/30)` naturalnie deprecjonuje źródła z małą próbką.
2. **Ważenie confluence** — probabilistyczne `1 - Π(1-score_i)` zamiast średniej.
3. **Stop-loss** — tier-based (large/mid/small cap), nie flat 5%.
4. **Spam** — top 3 per cykl + cooldown 2h per asset.
5. **Mierzenie skuteczności alertów** — `signal_outcomes` od pierwszego dnia.
6. **Horyzont score lookup** — Tier 1 i krypto Tier 2: `24h`; akcje Tier 2: `7d`.
