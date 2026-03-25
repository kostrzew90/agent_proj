# CLAUDE.md — Crypto Trading Agent

## Project Overview

Cryptocurrency trading agent built with:
- **Frontend**: Streamlit dashboard (Python)
- **Core Logic**: Technical indicators (RSI, MACD, EMA, Bollinger Bands, ATR), signal generation system, risk management
- **Orchestration**: APScheduler for recurring tasks
- **Exchange**: GATE.io Futures API (testnet mode by default)
- **Local LLM**: Ollama (qwen3 models) with Claude API as fallback
- **Database**: PostgreSQL with pgvector (port 5433)
- **Infrastructure**: Docker Compose for isolated trading stack

## Quick Start

```bash
# Start all services
docker-compose -f docker-compose-trading.yml up -d

# View logs
docker logs trading-app

# Access dashboard
http://localhost:8501
```

### Initial Setup

1. **Database schema**: Auto-initialized via `db-init/03-init-trading.sh`
2. **Configuration**: Copy `.env.example` to `.env` and configure:
   - `GATE_API_KEY` / `GATE_API_SECRET` (optional, uses testnet by default)
   - `ANTHROPIC_API_KEY` (Claude API fallback)
   - Risk parameters: `PAPER_TRADING`, `TRADING_ENABLED`, `MAX_LEVERAGE`, etc.

### Development Commands

```bash
pip install -r trading-app/requirements.txt
streamlit run trading-app/app.py
python trading-app/app.py
```

## Architecture

### Module Structure

```
trading-app/
├── core/
│   ├── database.py    # PostgreSQL/pgvector operations
│   ├── gate_api.py    # GATE.io Futures API client
│   ├── indicators.py  # Technical indicators (RSI, MACD, EMA, BB, ATR)
│   ├── signal_engine.py     # Signal generation with point-based scoring
│   ├── ollama_client.py     # LLM integration (Ollama primary, Claude backup)
│   └── scheduler.py   # APScheduler wrapper
│
├── tasks/
│   ├── market.py      # collect_market_data - fetch OHLCV, calculate indicators
│   ├── signals.py     # generate_signals - run signal engine
│   ├── monitor.py     # monitor_positions - check SL/TP
│   └── risk.py        # check_risk - daily loss limit, position sizing
│
├── config.py          # Dataclass-based configuration (all settings from .env)
├── app.py             # Streamlit entry point
└── requirements.txt
```

### Signal Generation System

Point-based scoring approach:
- Each technical condition awards points
- **LONG/SHORT signal**: triggered when total score >= 5
- Entry: ATR x 1.5 for stop loss, ATR x 3.0 for take profit

**Key conditions** (see `signal_engine.py`):
- RSI < 30 (+2 pts), < 20 (+3 pts) for LONG; > 70 (+2 pts), > 80 (+3 pts) for SHORT
- MACD crossovers (+2 pts)
- Bollinger Band extremes (+1 pt)
- EMA 200 trend alignment (+1 pt)
- Funding rate sentiment (+1 pt)

### Database Schema (PostgreSQL)

Key tables (auto-created in `db-init/03-init-trading.sh`):
- **market_indicators**: OHLCV + RSI, MACD, EMA, Bollinger, ATR (keyed on symbol+timestamp)
- **trading_signals**: Generated signals with score, confidence, reasoning
- **trading_positions**: Active positions (symbol, side, quantity, entry_price, SL, TP)
- **trading_position_history**: Closed positions with P&L
- **trading_orders**: Order history (from GATE.io)
- **trading_risk_config**: Risk parameters
- **indicator_config**: Threshold overrides

### Task Scheduling (APScheduler)

- **collect_market_data**: 60s
- **generate_signals**: 300s (5 min)
- **monitor_positions**: 30s
- **check_risk**: 60s
- **scan_liquidity**: 900s (15 min)

Each job: `coalesce=True`, `max_instances=1`.

## Key Configuration

### Risk Management (from `config.py`)

```python
PAPER_TRADING=true              # Simulate only (default)
TRADING_ENABLED=false           # Don't submit real orders (default)
DAILY_LOSS_LIMIT=2.0            # Stop trading if daily P&L < -2%
MAX_POSITION_SIZE=10.0          # Single position <= 10% of account
MAX_OPEN_POSITIONS=3
DEFAULT_LEVERAGE=5
```

### Indicators Configuration

Defaults match TradingView standards:
- RSI(14): oversold < 30, overbought > 70
- MACD(12,26,9), EMA(9,21,50,200), Bollinger(20,2std), ATR(14)

## Important Patterns

### Database Operations

```python
db = Database()
indicators = db.get_market_indicators(symbol="BTC_USDT", limit=100)
positions = db.get_open_positions()
db.insert_trading_signal(symbol, signal_type, score, confidence, reasoning)
```

### Error Handling in Tasks

```python
def collect_market_data():
    try:
        # fetch and store
    except Exception as e:
        logger.error(f"Market data collection failed: {e}")
```

### Streamlit Session State

Core objects cached in `st.session_state`: `scheduler`, `db`, `gate`, `ollama`. Avoid recreating on every rerun.

### API Integration

- **GATE.io**: `core/gate_api.py` — testnet by default; methods: `get_balance()`, `get_equity()`, `fetch_klines()`, `get_funding_rate()`, `place_order()`
- **Ollama**: `core/ollama_client.py` — HTTP `localhost:11434`, falls back to Claude API

## Common Tasks

### Add a New Technical Indicator
1. Implement in `core/indicators.py`
2. Store in `market_indicators` table
3. Add scoring in `core/signal_engine.py`
4. Add config in `config.py`

### Modify Signal Thresholds
Edit `config.py` or override via `.env`: `SIGNAL_MIN_SCORE=6`, `MAX_LEVERAGE=3`

## Database

- **Trading DB**: `localhost:5433` — user: `trading` / pass: `tradingpass` / db: `trading`

## Troubleshooting

| Issue | Check |
|-------|-------|
| Docker build fails | Verify `requirements.txt`; check Docker Desktop |
| DB connection error | `docker logs trading-postgres` — port 5433 free? |
| Ollama unavailable | Check `OLLAMA_URL` in .env |
| Signals not generating | Check `market_indicators` populated; verify thresholds |
| Position won't close | Check monitor task; verify SL/TP vs market |

## Key Files

- `koncepcja.md` — Full technical spec, decision log
- `db-init/03-init-trading.sh` — Full database schema
- `.env.example` — All configuration variables
- `docker-compose-trading.yml` — Full stack definition
