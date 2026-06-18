# Argus Signal Notifier — Design Spec

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Argus wysyła Telegramem alerty inwestycyjne z rekomendacją pozycji gdy wiarygodne źródła generują sygnał.

**Data:** 2026-06-18  
**Status:** Zaakceptowany przez usera, gotowy do implementacji.

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

### Dwa tryby wyzwalania

**Tier 1 — Whale Alert (tylko krypto, natychmiastowy)**

Wyzwalacz: HL whale z `decayed_score ≥ 0.60` i `n_claims ≥ 5` otwiera lub zmienia pozycję (nowy wpis w `wallet_positions` z ostatnich 10 minut).

Alert wysyłany w ciągu 10 minut od wykrycia.

**Tier 2 — Confluence Alert (krypto + akcje)**

Wyzwalacz: ≥ 2 źródła z **różnych kategorii** (`source.kind`) zgadzają się co do tego samego assetu i kierunku (bullish/bearish) w oknie **2 godzin**. Każde źródło musi mieć `decayed_score ≥ 0.60` i `n_claims ≥ 5`.

Alert wysyłany co 15 minut (job scan).

Różne `source.kind` = np. `reddit` + `hyperliquid`, `reddit` + `news`. Dwa źródła tego samego rodzaju nie tworzą confluence.

---

## Sizing recommendation

Formuła: `position% = risk% / stop_loss%`

| decayed_score (avg sygnału) | Ryzyko na trade | Stop krypto | Stop akcje | Pozycja krypto | Pozycja akcje |
|-----------------------------|-----------------|-------------|------------|---------------|---------------|
| 0.60 – 0.70                 | 1% portfela     | 5%          | 3%         | 20% portfela  | 33% portfela  |
| 0.70 – 0.80                 | 2% portfela     | 5%          | 3%         | 40% portfela  | 67% portfela  |
| 0.80+                       | 3% portfela     | 5%          | 3%         | 60% portfela  | max 50%       |

- Stop-loss: stały % (nie ATR) — prostota i testowalność
- Entry price: spot w momencie alertu; dla Tier 1 whale: cena otwarcia pozycji z `wallet_positions.entry_px`
- Akcje cap 50% — ogranicza koncentrację dla mniej płynnych aktywów

**Przykład:** SatoshiStreetBets (score 0.637) sygnalizuje bullish BTC@$67,400:
```
Ryzyko: 1% portfela
Stop: $64,030 (-5%)
Pozycja: 20% portfela
```

---

## Format wiadomości Telegram

**Tier 1 — Whale:**
```
🐋 WHALE SIGNAL · BULLISH ETH/USDT

Whale: 0x9321...d75a
Score: 0.60 · 75% hit@24h · n=8
Pozycja: $2.1M long @ $3,420

Entry teraz: ~$3,445
Stop-loss: $3,273 (-5%)
Pozycja: 20% portfela (ryzyko 1%)
Horyzont: 24h
```

**Tier 2 — Confluence:**
```
⚡ CONFLUENCE · BULLISH BTC/USDT

• r/SatoshiStreetBets · 0.64 · 80%@24h
• HL whale 0x5078 · 0.60 · 60%@24h
Zgodność: 2 źródła · okno 1h45m

Entry teraz: ~$67,400
Stop-loss: $64,030 (-5%)
Pozycja: 20% portfela (ryzyko 1%)
Horyzont: 24h
```

---

## Architektura

### Nowe pliki

**`argus/signals.py`**
- `check_whale_signals(session) -> list[SignalResult]` — skanuje nowe `wallet_positions`
- `check_confluence_signals(session) -> list[SignalResult]` — grupuje claimy po asset+direction w oknie 2h
- `compute_sizing(avg_score: float, asset_type: str) -> dict` — zwraca `{risk_pct, stop_pct, position_pct}`
- `format_signal_message(signal: SignalResult) -> str` — formatuje tekst Telegram

**`argus/telegram.py`**
- `send_message(text: str) -> None` — POST do Telegram Bot API
- Reużywa `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` z `.env` (ten sam bot co Guardian)

### Zmiany w istniejących plikach

**`argus/models.py`**
Nowa tabela `signal_log`:
```python
class SignalLog(Base):
    __tablename__ = "signal_log"
    id: int (PK)
    tier: str          # "whale" | "confluence"
    asset: str         # "BTC"
    direction: str     # "bullish" | "bearish"
    source_ids: str    # JSON list of source IDs
    avg_score: float
    sent_at: datetime
```

Używana do cooldown checking i historii sygnałów.

**`argus/main.py`**
Dwa nowe jopy w schedulerze:
- `_whale_signal_job` — co 10 minut
- `_confluence_signal_job` — co 15 minut

### Cooldown

- **2h per asset** — żaden asset nie generuje więcej niż 1 alertu na 2 godziny (niezależnie od tier)
- Sprawdzane przez `signal_log.sent_at` + `signal_log.asset`

### Flow danych

```
_whale_signal_job (co 10min)
  → wallet_positions WHERE created_at > now()-10min
  → JOIN sources WHERE decayed_score >= 0.60 AND n_claims >= 5
  → cooldown check (signal_log, asset, 2h)
  → compute_sizing()
  → format_signal_message()
  → send_message()
  → INSERT signal_log

_confluence_signal_job (co 15min)
  → claims WHERE entry_ts > now()-2h
  → JOIN sources WHERE decayed_score >= 0.60 AND n_claims >= 5
  → GROUP BY (asset, direction)
  → FILTER: >= 2 różne source.kind w grupie
  → cooldown check
  → compute_sizing()  [avg_score = średnia source scores w grupie]
  → format_signal_message()
  → send_message()
  → INSERT signal_log
```

---

## Out of scope

- Exit signals (kiedy wyjść z pozycji) — poza zakresem tego incrementu
- Auto-execution przez API giełdy — ręczne wykonanie przez usera
- Portfolio tracking (ile mam otwartych pozycji) — poza zakresem
- Push notifications inne niż Telegram

---

## Progi kwalifikacyjne — podsumowanie

| Parametr | Wartość |
|---|---|
| Min decayed_score | ≥ 0.60 |
| Min n_claims źródła | ≥ 5 |
| Confluence: min źródeł | 2 z różnych `kind` |
| Confluence: okno czasowe | 2h |
| Cooldown per asset | 2h |
| Tier 1 scan interval | 10 min |
| Tier 2 scan interval | 15 min |

---

## Otwarte pytania (do rozwiązania przed implementacją)

1. **n_claims z `source_scores` czy z `claims`?** — `source_scores.n_claims` to liczba ewaluowanych claimów per horyzont. Dla warunku kwalifikacyjnego brać max po wszystkich horyzontach danego źródła.
2. **Horyzont do score lookup dla Tier 2 akcji?** — brać `decayed_score` z horyzontu `7d` (swing). Dla krypto Tier 2: `24h`.
3. **Co jeśli Telegram bot jest niedostępny?** — log error, nie retry (sygnał jest time-sensitive, stary alert jest bezużyteczny).
