# Koncepcja Trading Agenta - Notatki

> Ostatnia aktualizacja: 2026-02-01
> Plan szczegółowy: `C:\Users\DAMA\.claude\plans\luminous-launching-harbor.md`

---
## PO POWROCIE - ZACZNIJ TUTAJ

**Stan:** Implementacja core GOTOWA. Nie uruchomiono jeszcze stacka.

**Co zrobić:**
1. Uruchom stack: `docker-compose -f docker-compose-trading.yml up -d`
2. Sprawdź logi: `docker logs trading-app`
3. Otwórz dashboard: http://localhost:8501
4. Opcjonalnie: uzupełnij klucze GATE.io w `trading-app/.env`

**Ewentualne problemy:**
- Jeśli błędy importu → sprawdź requirements.txt
- Jeśli brak połączenia z Ollama → upewnij się że Ollama działa na Windows
- Jeśli błędy bazy → sprawdź czy postgres wystartował (`docker logs trading-postgres`)

---

## Status projektu

- [x] Analiza koncepcji z pliku źródłowego
- [x] Zbadanie obecnego stacka (n8n, PostgreSQL, Ollama)
- [x] Zaprojektowanie architektury
- [x] Plan zatwierdzony
- [x] Dodano wskaźniki techniczne (RSI, MACD, EMA, BB, ATR)
- [x] Zdefiniowano logikę decyzyjną (warunki wejścia/wyjścia)
- [x] **Schemat bazy danych** (`db-init/03-init-trading.sh`)
- [x] **Core modules** (database, gate_api, ollama_client, indicators, signal_engine, scheduler)
- [x] **Tasks** (market, signals, monitor, risk)
- [x] **Docker Compose** (`docker-compose-trading.yml` - osobny stack)
- [x] **Streamlit app** (app.py - podstawowy dashboard)
- [ ] **Testowanie na danych demo** (następny krok)
- [ ] **Pages GUI** (Dashboard, Signals, Positions, Risk, Knowledge, Settings)

## Zrealizowane pliki

```
n8n/
├── docker-compose.yml              # Oryginalny (bez zmian)
├── docker-compose-trading.yml      # NOWY - osobny stack dla bota
├── koncepcja.md                    # Ten plik
│
├── db-init/
│   ├── 01-init-crawl4ai-db.sh
│   ├── 02-init-embeddings.sh
│   └── 03-init-trading.sh          # NOWY - schemat bazy tradingowej
│
└── trading-app/                    # NOWY - cała aplikacja
    ├── app.py                      # Streamlit entry point
    ├── config.py                   # Konfiguracja
    ├── requirements.txt            # Dependencies
    ├── .env                        # Zmienne środowiskowe
    ├── .env.example
    │
    ├── core/
    │   ├── __init__.py
    │   ├── database.py             # PostgreSQL + pgvector client
    │   ├── gate_api.py             # GATE.io Futures API
    │   ├── ollama_client.py        # Ollama LLM + Claude backup
    │   ├── indicators.py           # RSI, MACD, EMA, BB, ATR
    │   ├── signal_engine.py        # Logika sygnałów (system punktowy)
    │   └── scheduler.py            # APScheduler
    │
    ├── tasks/
    │   ├── __init__.py
    │   ├── market.py               # Pobieranie danych OHLCV
    │   ├── signals.py              # Generowanie sygnałów
    │   ├── monitor.py              # Monitoring pozycji SL/TP
    │   └── risk.py                 # Kontrola ryzyka
    │
    ├── pages/
    │   └── __init__.py             # (do implementacji)
    │
    └── utils/
        └── __init__.py
```

## Kluczowe decyzje

| Aspekt | Decyzja |
|--------|---------|
| GUI | Streamlit Dashboard (port 8501) |
| Orchestracja | APScheduler wbudowany w Streamlit |
| Baza danych | **Osobna instancja PostgreSQL** (port 5433) |
| LLM główny | Ollama (qwen3:4b) |
| LLM backup | Claude API |
| Embeddingi | Ollama qwen3-embedding:0.6b (1024 dim) |
| Giełda | GATE.io Futures (testnet) |

## Uruchomienie

```bash
# 1. Uzupełnij klucze API
notepad trading-app\.env

# 2. Uruchom stack
docker-compose -f docker-compose-trading.yml up -d

# 3. Otwórz dashboard
# http://localhost:8501
```

**Porty:**
- `8501` - Trading Dashboard (Streamlit)
- `5433` - PostgreSQL (osobna instancja)
- `9998` - Dozzle (logi)

## Wskaźniki Techniczne

### Konfiguracja RSI
| Poziom | Wartość | Akcja |
|--------|---------|-------|
| Extreme Oversold | < 20 | Silny sygnał LONG (+3 pkt) |
| Oversold | < 30 | Sygnał LONG (+2 pkt) |
| Neutral | 40-60 | Brak sygnału |
| Overbought | > 70 | Sygnał SHORT (+2 pkt) |
| Extreme Overbought | > 80 | Silny sygnał SHORT (+3 pkt) |

### Wszystkie wskaźniki
- **RSI** (14) - wykupienie/wyprzedanie
- **MACD** (12/26/9) - momentum, crossovers
- **EMA** (9, 21, 50, 200) - trend direction
- **Bollinger Bands** (20, 2std) - volatility
- **ATR** (14) - stop loss sizing
- **Funding Rate** - sentiment (z GATE.io)

### Logika decyzyjna
- **Próg wejścia:** suma punktów >= 5
- **Stop Loss:** ATR * 1.5
- **Take Profit:** ATR * 3.0
- **Trailing Stop:** po zysku > 2%

### Warunki wejścia LONG
1. RSI < 30 (+2) lub RSI < 20 (+3)
2. MACD crossover UP (+2)
3. Cena < BB lower (+1)
4. Cena > EMA 200 (+1)
5. Blisko support level (+2)
6. Negative funding (+1)

### Warunki wejścia SHORT
1. RSI > 70 (+2) lub RSI > 80 (+3)
2. MACD crossover DOWN (+2)
3. Cena > BB upper (+1)
4. Cena < EMA 200 (+1)
5. Blisko resistance level (+2)
6. High positive funding (+1)

## Następne kroki

1. **Testowanie na demo** - uruchomić stack, sprawdzić połączenia
2. **Uzupełnić klucze GATE.io** - testnet API keys
3. **Zweryfikować wskaźniki** - porównać z TradingView
4. **Dodać pages GUI** - rozbudować dashboard
5. **Paper trading** - symulacja na realnych danych

## Tabele w bazie danych

```
trading_risk_config        - Konfiguracja ryzyka
indicator_config           - Progi wskaźników
market_indicators          - OHLCV + RSI, MACD, EMA, BB, ATR
market_liquidity_levels    - Wsparcia/opory
trading_signals            - Wygenerowane sygnały
trading_orders             - Historia zleceń
trading_positions          - Aktywne pozycje
trading_position_history   - Zamknięte pozycje (P&L)
onchain_metrics            - Dane Glassnode
knowledge_embeddings       - Embeddingi wiedzy
trading_audit_log          - Audit trail
account_snapshots          - Dzienne snapshoty konta
```

## Bezpieczeństwo

- Domyślnie `PAPER_TRADING=true`
- Domyślnie `TRADING_ENABLED=false`
- API keys w `.env` (nie w kodzie)
- Osobna baza danych (izolacja od n8n)
- Daily loss limit: 2%
- Max pozycja: 10% kapitału
- Max leverage: 10x

## Źródło koncepcji

Plik: `c:\Users\DAMA\OneDrive\Dam\agent\koncepcja trading agent i bazy z danymi do analizy.txt`
