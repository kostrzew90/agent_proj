# Argus Signal Notifier — Design Spec

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Argus wysyła Telegramem alerty inwestycyjne z rekomendacją pozycji gdy wiarygodne źródła generują sygnał.

**Data:** 2026-06-18
**Status:** Zaakceptowany. Dwie rundy recenzji (user + Opus) zintegrowane.

---

## Kontekst

Argus od ~15 dni uczy się wiarygodności źródeł (hit_rate per source per horyzont). Zebrane dane (scorer rankings z 2026-06-18):

- **Najlepsze:** r/SatoshiStreetBets (80% hit@24h, n=5), HL whale 0x9321 (75% hit@24h, n=4)
- **Słabe:** r/CryptoCurrency (26% hit@24h, n=66), Yahoo Finance (~17%)

Brakuje warstwy która **działa na tych naukach** — system zbiera i ocenia, ale nie powiadamia.

---

## Strategia sygnałów

### Horyzont inwestycyjny

- **Krypto:** short-term (24h)
- **Akcje:** swing (7d)

### Scoring — dwa zastosowania effective_score

`effective_score` służy **wyłącznie do sizingu** (im więcej danych, tym większa pozycja). Do przejścia gateów używany jest surowy `decayed_score` z twardym progiem `n_claims`.

```
effective_score = decayed_score × min(1.0, n_claims / 30)
```

`n_claims` = max po wszystkich horyzontach z `source_scores` dla danego źródła (nie `source_asset_scores` — per-coin ma n=1-2 i byłoby gorsze).

Horyzont score lookup: krypto → `24h`, akcje → `7d`.

### Gate kwalifikacyjny (wejście do sygnału)

Twarde progi — żadnych mnożników:

```
decayed_score ≥ 0.60  AND  n_claims ≥ 5
```

Przy obecnych danych (n=4-5) kilka źródeł jest na granicy — system będzie milczeć dopóki nie uzbiera n≥5 na horyzoncie 24h. To jest zamierzone: lepiej zero sygnałów niż szum.

Tylko `source.kind in ('hyperliquid', 'reddit', 'news', 'rss')` — macro/FRED/edgar wykluczone z gateów (kierunek macro nie mapuje się na trade).

### Tier 1 — Whale Alert (tylko krypto, natychmiastowy)

Wyzwalacz: HL whale który przeszedł gate otwiera lub flips pozycję — nowy wpis w `wallet_positions` z ostatnich 10 minut.

Alert w ciągu 10 minut. Tier 1 nie wymaga confluence.

### Tier 2 — Confluence Alert (krypto + akcje)

Wyzwalacz: ≥ 2 źródła z **różnych `source.kind`** zgadzają się co do assetu i kierunku w oknie **2 godzin**. Każde źródło musi przejść gate.

Dwa źródła tego samego kind (np. 2 subreddity) = nie confluence.

Siła confluence (probabilistyczna, nie średnia):
```
combined_strength = 1 − Π(1 − effective_score_i)
```

Minimalne progi:
- `combined_strength ≥ 0.80` (próg podniesiony z 0.75 — przy 2×0.60 daje 0.84, przy 2×0.55 daje 0.80, więc realny filtr)
- Maksymalnie **top 3 sygnały per cykl** (ranking po `combined_strength`) — ochrona przed spamem gdy rynek rusza wiele assetów naraz

Scan co 15 minut.

---

## Sizing recommendation

### Entry price

- **Tier 1 whale:** `wallet_positions.entry_px` (faktyczna cena wejścia whala)
- **Tier 2 confluence:** ostatnia cena z tabeli `prices` dla danego assetu (już istnieje w systemie)

### Stop-loss według volatility tier

Stały % (nie ATR — jawnie poza scope). Tier assignowany per asset w `config/assets.yaml` (pole `vol_tier`):

| Vol tier | Przykłady | Stop krypto | Stop akcje |
|---|---|---|---|
| large | BTC, ETH | 5% | 3% |
| mid | SOL, ADA, AVAX, większość akcji | 7% | 4% |
| small | DOGE, SHIB, mniejsze alts | 10% | 5% |

Default: `mid`.

### Formuła i limity

**Krypto (futures — dźwignia możliwa):**
```
position% = risk% / stop%
```

**Akcje (spot — bez dźwigni):**
```
position% = min(risk% / stop%, 15%)
```
Cap 15% bo 60% w jeden ticker na spocie jest niewykonalne.

| Signal strength (effective_score / combined_strength) | Ryzyko na trade |
|---|---|
| 0.55 – 0.75 | 1% portfela |
| 0.75 – 0.90 | 2% portfela |
| 0.90+ | 3% portfela |

**Przykład** — Whale (decayed=0.75, n=8, effective=0.20) otwiera long BTC@$67,400 (large cap):
- Gate: 0.75 ≥ 0.60 ✓, n=8 ≥ 5 ✓
- Sizing: effective=0.20 → ryzyko 1%
- Stop: $64,030 (-5%)
- Pozycja: 1%/5% = **20% portfela**

---

## Format wiadomości Telegram

**Tier 1 — Whale:**
```
🐋 WHALE SIGNAL · BULLISH ETH/USDT

Whale: 0x9321...d75a
Score: 0.60 (75%@24h, n=8)
Pozycja whale: $2.1M long @ $3,420

Entry teraz: ~$3,445
Stop-loss: $3,273 (-5%, large cap)
Pozycja: 20% portfela (ryzyko 1%)
Horyzont: 24h
```

**Tier 2 — Confluence:**
```
⚡ CONFLUENCE · BULLISH BTC/USDT · strength 0.84

• r/SatoshiStreetBets · 0.64 · 80%@24h · n=12
• HL whale 0x5078 · 0.61 · 60%@24h · n=6
Zgodność: 2 źródła · okno 1h45m

Entry teraz: ~$67,400
Stop-loss: $64,030 (-5%, large cap)
Pozycja: 20% portfela (ryzyko 1%)
Horyzont: 24h
```

Telegram błąd → log warning, nie retry (sygnał time-sensitive, stary alert bezużyteczny).

---

## Architektura

### Nowe pliki

**`argus/signals.py`**
- `passes_gate(decayed_score: float, n_claims: int) -> bool`
- `effective_score(decayed_score: float, n_claims: int) -> float`
- `combined_strength(scores: list[float]) -> float`
- `compute_sizing(strength: float, vol_tier: str, asset_type: str) -> dict`
- `check_whale_signals(session) -> list[SignalResult]`
- `check_confluence_signals(session) -> list[SignalResult]`
- `format_signal_message(signal: SignalResult) -> str`

**`argus/telegram.py`**
- `send_message(text: str) -> None`
- Wzorzec z `guardian/telegram.py` (POST sendMessage, swallow errors + log)
- Env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (już w `.env` na VPS)

### Zmiany w istniejących plikach

**`argus/models.py`** — dwie nowe tabele:

```python
class SignalLog(Base):
    __tablename__ = "signal_log"
    id: int (PK)
    tier: str           # "whale" | "confluence"
    asset: str
    direction: str      # "bullish" | "bearish"
    source_ids: str     # JSON list
    signal_strength: float
    entry_price: float
    stop_price: float
    position_pct: float
    sent_at: datetime

class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    id: int (PK)
    signal_id: int      # FK signal_log.id
    asset: str
    entry_price: float
    price_24h: float | None
    price_7d: float | None
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    hit_stop: bool | None
    outcome: str | None  # "win" | "loss" | "stopped" | "open"
    evaluated_at: datetime | None
```

`signal_outcomes` to najważniejsza tabela projektu — po 2-3 miesiącach pozwoli mierzyć skuteczność alertów (nie tylko źródeł) i stroić progi automatycznie.

**`argus/main.py`** — trzy nowe jopy:
- `_whale_signal_job` — co 10 min
- `_confluence_signal_job` — co 15 min
- `_signal_outcomes_job` — co 6h (ewaluuje otwarte sygnały ≥24h)

### Cooldown

**2h per asset, cross-tier** — jeden cooldown obejmuje oba tiery. Whale alert na BTC blokuje confluence alert na BTC przez 2h. Sprawdzane atomowo z `signal_log` przed każdym `send_message`.

### Flow danych

```
_whale_signal_job (co 10min)
  → wallet_positions WHERE created_at > now()-10min
  → JOIN source_scores WHERE decayed_score >= 0.60 AND n_claims >= 5
  → cooldown check (signal_log, asset, 2h) — cross-tier
  → compute_sizing(effective_score, vol_tier, "crypto")
  → entry_price = wallet_positions.entry_px
  → format + send_message()
  → INSERT signal_log + signal_outcomes(outcome="open")

_confluence_signal_job (co 15min)
  → claims WHERE entry_ts > now()-2h AND source.kind IN ('hyperliquid','reddit','news','rss')
  → JOIN source_scores WHERE decayed_score >= 0.60 AND n_claims >= 5
  → GROUP BY (asset, direction)
  → FILTER: >= 2 różne source.kind w grupie
  → combined_strength = 1 - Π(1 - effective_score_i)
  → FILTER: combined_strength >= 0.80
  → SORT DESC, TAKE top 3
  → cooldown check per asset — cross-tier
  → entry_price = last price FROM prices WHERE asset=asset
  → compute_sizing(combined_strength, vol_tier, asset_type)
  → format + send_message()
  → INSERT signal_log + signal_outcomes(outcome="open")

_signal_outcomes_job (co 6h)
  → signal_outcomes WHERE outcome="open" AND signal_log.sent_at < now()-24h
  → fetch price (prices table lub yfinance/Binance fallback)
  → update price_24h/price_7d, hit_stop, MFE, MAE
  → outcome = "stopped" jeśli hit_stop, "win" jeśli price > entry+stop, "loss" inaczej
  → log summary
```

---

## Out of scope

- Exit signals
- Auto-execution przez API giełdy
- Portfolio tracking
- ATR-based stop-loss

---

## Progi — podsumowanie

| Parametr | Wartość | Uzasadnienie |
|---|---|---|
| Gate: min decayed_score | ≥ 0.60 | twardo, bez mnożnika |
| Gate: min n_claims | ≥ 5 | twardo |
| effective_score mnożnik | n/30 | tylko do sizingu, nie do gate |
| Confluence: min źródeł | 2 z różnych kind | dekorelacja |
| Confluence: min combined_strength | ≥ 0.80 | realny filtr |
| Confluence: okno | 2h | |
| Confluence: max per cykl | top 3 | antyspam |
| Cooldown per asset | 2h cross-tier | |
| Akcje: cap pozycji | 15% | spot limit |
| Tier 1 scan | co 10 min | |
| Tier 2 scan | co 15 min | |
| Outcomes eval | co 6h | |
