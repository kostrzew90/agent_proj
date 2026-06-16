# Batch LLM Gap-Fill — Design Spec

**Date:** 2026-06-17  
**Status:** Approved  

## Problem

LLM gap-fill działa inline w `collect_rss` (co 30min). Skutki:
- ~50+ callów/dzień → wyczerpuje free quotas (Gemini RPD, OpenRouter)
- `entry_price = get_spot_price()` zamiast ceny z momentu publikacji → zaszumia scoring gdy item czeka w kolejce

## Rozwiązanie

Rozdzielić "wykrycie gapu" (collect_rss, co 30min) od "wywołania LLM" (batch job, co 2h). Max 96 callów/dzień (8 items × 12 runów).

## Zakres źródeł

| source.kind | LLM gap-fill | Uzasadnienie |
|-------------|--------------|--------------|
| `reddit`    | ✅ tak       | Najwyższy yield, slang/ironia których rule-v2 nie łapie |
| `news`      | ✅ tak       | Jedyna dyrekcyjna ścieżka dla akcji (inferencja z faktu) |
| `rss`       | ❌ nie       | Niski yield, duplikuje makro-prior z FRED, wypierałby lepsze itemy z batcha |

## Architektura

```
collect_rss (co 30min)
  └─ rule-v2 gap + source.kind in ("reddit", "news")
       └─ enqueue_for_llm() → llm_queue [status=pending]
                                    ↓
_llm_batch_job (co 2h, max 8 items/run)
  └─ SELECT pending ORDER BY kind=reddit DESC, enqueued_at DESC LIMIT 8
       ├─ cache hit  → create claim, status=done (bez LLM call)
       └─ cache miss → call LLM → cache_put → create claim, status=done
              entry_price = get_historical_price(asset, item.published_at)
              entry_ts    = item.published_at
              fallback    = get_spot_price() gdy published_at=None lub API error
```

## Nowa tabela: `llm_queue`

```python
class LlmQueue(Base):
    __tablename__ = "llm_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), unique=True)  # dedup
    text_hash: Mapped[str] = mapped_column(String)       # cache lookup
    source_kind: Mapped[str] = mapped_column(String)     # reddit|news — dla ORDER BY bez joina
    status: Mapped[str] = mapped_column(String)          # pending|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
```

Tworzona przez `Base.metadata.create_all(engine)` w bootstrap — Alembic nie używany w projekcie.

## Zmiany w `collect_rss` (argus/collectors/rss.py)

**Usuwa:**
- Klasa `LlmBudget` 
- Import i wywołanie `extract_claims_llm`
- Import i wywołanie `cache_get`/`cache_put` (zostają w batch.py)
- Inline cache check + claim creation dla cache hits

**Dodaje:**
- Import `enqueue_for_llm` z `argus.llm.batch`
- Gdy `rule_pcs` puste AND `source.kind in ("reddit", "news")`: wywołaj `enqueue_for_llm(session, item, text)`

**Pozostaje bez zmian:**
- Rule claim creation (spot price, entry_ts=now — item przetwarzany natychmiast)
- Logowanie `stats`; `stats["gap"]` → `stats["enqueued"]`

## Nowy moduł: `argus/llm/batch.py`

### `enqueue_for_llm(session, item, text) -> bool`

```python
def enqueue_for_llm(session, item: Item, source_kind: str, text: str) -> bool:
    from argus.llm.cache import text_hash
    h = text_hash(text)
    if session.scalar(select(LlmQueue).where(LlmQueue.item_id == item.id)):
        return False  # already queued or processed
    session.add(LlmQueue(item_id=item.id, text_hash=h, source_kind=source_kind,
                         status="pending", attempts=0,
                         enqueued_at=datetime.now(timezone.utc)))
    return True
```

### `process_llm_batch(session, batch_size, assets, sector_map) -> dict`

Algorytm:
1. Pobierz `batch_size` wpisów: `status=pending AND attempts < MAX_ATTEMPTS`, sort: `reddit` przed `news` (ORDER BY CASE), potem `enqueued_at DESC` (najnowsze first — wyższy sygnał dla 1h/24h horyzontów)
2. Dla każdego wpisu:
   a. Pobierz `Item` — jeśli brak: `status=failed`, skip
   b. Sprawdź cache (`cache_get(session, entry.text_hash)`)
   c. Cache hit → `triples` z cache
   d. Cache miss → `extract_claims_llm(item.text, assets, sector_map)` → na sukces: `cache_put()`, `triples` z wyniku
   e. LLM exception → `entry.attempts += 1`, `entry.last_error = str(e)[:300]`, jeśli `attempts >= MAX_ATTEMPTS`: `status=failed`, commit, continue (nie cache)
3. Dla każdego `(sym, direction, reasoning)` z `triples`:
   - Pobierz `asset` z `by_symbol`; skip jeśli brak
   - `ts = item.published_at or item.fetched_at`
   - `entry_price = get_historical_price(asset, ts)` z fallback `get_spot_price(asset)`
   - Utwórz `Claim(entry_price=entry_price, entry_ts=ts, method="llm", ...)`
4. `entry.status = "done"`, `entry.processed_at = now()`, commit
5. Zwróć stats: `{processed, cache_hits, llm_calls, claims, errors}`

**Stałe:**
- `MAX_ATTEMPTS = 5`
- Priorytet kolejki: reddit=0, news=1 (ORDER BY CASE kind WHEN 'reddit' THEN 0 ELSE 1 END)

### Sortowanie kolejki — uzasadnienie

Reddit → news priority: Reddit ma wyższy yield claimów. Bez priorytetu zalew reddit mógłby blokować news items, które jako jedyne dają sygnał dla akcji. Najnowsze first: świeży claim wart więcej dla 1h/24h horyzontów scoringu.

## Zmiany w `main.py`

```python
from argus.llm.batch import process_llm_batch
from argus.collectors.rss import load_sector_map

def _llm_batch_job():
    batch_size = int(os.getenv("ARGUS_LLM_BATCH_SIZE", "8"))
    assets = []
    with SessionLocal() as s:
        assets = list(s.scalars(select(Asset).where(Asset.scorable == True)))  # noqa: E712
        sector_map = load_sector_map()
        stats = process_llm_batch(s, batch_size, assets, sector_map)
    logger.info("llm_batch: %s", stats)

# w bootstrap():
sched.add_interval("llm_batch", _llm_batch_job, minutes=120)
```

## Entry price — semantyka

| Sytuacja | entry_price | entry_ts |
|----------|------------|----------|
| Rule claim | `get_spot_price()` | `now` (item przetwarzany natychmiast) |
| LLM batch claim | `get_historical_price(asset, published_at)` → fallback spot | `item.published_at` |

Uzasadnienie: batch job przetwarza item z opóźnieniem do 2h. Cena wejścia z momentu publikacji = uczciwy pomiar wiarygodności źródła. Zakotwiczyć w `published_at` = cena którą trader miał dostępną czytając artykuł.

`get_historical_price` już istnieje w `argus/prices.py` (Binance klines dla crypto, yfinance history dla stocks). Fallback na spot gdy `published_at=None` lub API error.

## Zmiany w `argus/models.py`

Dodać klasę `LlmQueue` (nowa tabela). Brak zmian w istniejących modelach.

## Out of scope

- Dashboard dla llm_queue (status pending/done/failed) — przyszłość
- Priorytetyzacja dynamiczna wg source.decayed_score — przyszłość
- Retry z exponential backoff między attempts — nie potrzebne (batch co 2h naturalnie spacuje)

## Testy

| Test | Co weryfikuje |
|------|--------------|
| `test_enqueue_dedup` | Ten sam item_id → 1 wpis w kolejce (unique constraint) |
| `test_enqueue_rss_skipped` | source.kind=rss → nie trafia do kolejki |
| `test_enqueue_reddit_news_ok` | reddit i news trafiają do kolejki |
| `test_batch_cache_hit` | Cache hit → claim tworzony bez LLM call |
| `test_batch_llm_called` | Cache miss → LLM call → cache_put → claim |
| `test_batch_entry_price_from_published_at` | entry_ts = item.published_at, entry_price = historical |
| `test_batch_entry_price_fallback` | published_at=None → fallback na spot |
| `test_batch_llm_error_retry` | LLM exception → attempts++, max attempts → status=failed |
| `test_batch_priority_order` | reddit items przetwarzane przed news |
| `test_collect_rss_no_inline_llm` | collect_rss nie wywołuje extract_claims_llm |

## Env vars

| Var | Default | Opis |
|-----|---------|------|
| `ARGUS_LLM_BATCH_SIZE` | `8` | Items per batch run |
| `ARGUS_LLM_MAX_ATTEMPTS` | `5` | Max retry przed failed |
