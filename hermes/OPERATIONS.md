# Hermes — lista operacji automatycznych

Plik opisuje wszystkie zadania cykliczne uruchamiane przez Hermesa.
Edycja: zmień `interval_s` / `enabled` bezpośrednio w `bridge/hermes_bridge.py:54-98`, a potem `docker compose restart hermes-bridge`.

---

## Cron jobs (`hermes-bridge`)

Silnik: wątek tła w `bridge/hermes_bridge.py`, tick co 60s.  
Sterowanie przez Telegrama: `/cron`, `/cron on <name>`, `/cron off <name>`, `/cron run <name>`.

| Nazwa | Częstotliwość | Godzina | Telegram | Opis |
|---|---|---|---|---|
| `pool-monitor` | co 30 min | — | cicho (log only) | Scrape liczby osób na basenie Nieporęt → CSV (`audit/pool-YYYY-MM.csv`) + Postgres |
| `scan-rss` | co 24h | 8:00 | zawsze | **WYŁĄCZONY** — reaktywacja: `HERMES_ENABLE_LEGACY_CRONS=1` w `.env` + restart |
| `daily-digest` | co 24h | 7:00 | zawsze | **WYŁĄCZONY** |
| `crypto-arbitrage` | co 1h | — | tylko alert | **WYŁĄCZONY** |
| `auto-todo` | co 6h | — | zawsze | **WYŁĄCZONY** |
| `classify-tabs` | co 6h | — | cicho | **WYŁĄCZONY** |
| `recompute-importance` | co 6h | — | cicho | **WYŁĄCZONY** |
| `check-confirmations` | co 6h | — | tylko alert | **WYŁĄCZONY** |
| `review-learn` | co 3h | — | zawsze | **WYŁĄCZONY** |

### Reaktywacja legacy jobów

Dodaj do `hermes/.env`:
```
HERMES_ENABLE_LEGACY_CRONS=1
```
Następnie: `docker compose -f hermes/docker-compose.yml restart hermes-bridge`

### Tryby notify
- `always` — wynik zawsze trafia na Telegrama
- `on_alert` — tylko gdy skill zwróci alert (spread > threshold, pending confirmations itd.)
- `silent` — tylko do `audit/cron.log`, brak Telegrama

---

## Ingest tabów (`hermes-ingest`)

Kod: `hermes-ingest/main.py`, kontener `hermes-ingest`.  
Env var do zmiany interwału: `INGEST_INTERVAL_SEC` (default: `3600`).

| Operacja | Częstotliwość | Opis |
|---|---|---|
| `run_cycle` | co 1h | Pobiera otwarte zakładki Chrome przez CDP → chunking → embedding (qwen3-embedding:0.6b) → zapis do Postgres (RAG DB) z deduplikacją |

---

## Polling inbox (`hermes-bridge`)

| Operacja | Częstotliwość | Opis |
|---|---|---|
| Inbox scan | co 2s | Skanuje `audit/inbox/` w poszukiwaniu wiadomości od telegram-watchera. Stała — nie jest cron jobem, nie ma sensu zmieniać. |

---

## Host watchdog

Kod: `scripts/heartbeat-watchdog.sh`.  
Wymaga wpisu w crontab hosta (jeszcze **nie skonfigurowany**):

```
*/5 * * * * /ścieżka/do/hermes/scripts/heartbeat-watchdog.sh >> /var/log/hermes-watchdog.log 2>&1
```

| Operacja | Częstotliwość (host cron) | Opis |
|---|---|---|
| Heartbeat watchdog | co 5 min | Czyta `audit/heartbeat.txt` — jeśli ostatni heartbeat starszy niż 60 min, uruchamia killswitch i wysyła alert na Telegrama |

---

## Telegram komendy do zarządzania

```
/cron                    # lista wszystkich jobów z statusem i ostatnim uruchomieniem
/cron on <name>          # włącz job
/cron off <name>         # wyłącz job
/cron run <name>         # natychmiastowe uruchomienie
/status                  # status kontenerów + ostatni heartbeat + costs
/stop                    # killswitch (zatrzymuje wszystkie kontenery Hermesa)
```

---

## Jak dodać nową operację

1. Dodaj wpis do `_CRON_JOBS` w `bridge/hermes_bridge.py:54`:
   ```python
   "moja-operacja": {
       "interval_s": 3600,       # sekundy
       "run_at_hour": None,       # None = bez godziny, int = o tej godzinie
       "enabled": True,
       "last_run": 0.0,
       "description": "Opis co robi",
       "notify": "always",        # always | on_alert | silent
   },
   ```
2. Dodaj obsługę nazwy w `_cron_execute_skill()` (`bridge/hermes_bridge.py` ~linia 1307).
3. Dodaj wpis w tej tabeli powyżej.
4. `docker compose restart hermes-bridge`
