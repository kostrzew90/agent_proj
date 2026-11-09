
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
