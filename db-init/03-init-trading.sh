#!/bin/bash
set -e

# Create tables for Trading Agent
# Uses POSTGRES_USER and POSTGRES_DB from environment
psql -v ON_ERROR_STOP=0 --username "${POSTGRES_USER:-trading}" --dbname "${POSTGRES_DB:-trading}" <<-EOSQL

    -- =============================================
    -- TRADING AGENT SCHEMA
    -- =============================================

    -- Konfiguracja ryzyka i parametrów tradingu
    CREATE TABLE IF NOT EXISTS trading_risk_config (
        id SERIAL PRIMARY KEY,
        config_key VARCHAR(50) UNIQUE NOT NULL,
        config_value TEXT NOT NULL,
        description TEXT,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- Domyślne wartości konfiguracji
    INSERT INTO trading_risk_config (config_key, config_value, description) VALUES
        ('paper_trading_mode', 'true', 'Tryb paper trading (bez realnych transakcji)'),
        ('trading_enabled', 'false', 'Czy trading jest włączony'),
        ('daily_loss_limit_percent', '2.0', 'Maksymalna dzienna strata (%)'),
        ('max_position_size_percent', '10.0', 'Maksymalny rozmiar pozycji (% kapitału)'),
        ('max_open_positions', '3', 'Maksymalna liczba otwartych pozycji'),
        ('default_leverage', '5', 'Domyślna dźwignia'),
        ('max_leverage', '10', 'Maksymalna dozwolona dźwignia'),
        ('min_signal_score', '5', 'Minimalny score sygnału do otwarcia pozycji'),
        ('atr_sl_multiplier', '1.5', 'Mnożnik ATR dla stop loss'),
        ('atr_tp_multiplier', '3.0', 'Mnożnik ATR dla take profit'),
        ('trailing_stop_activation', '2.0', 'Aktywacja trailing stop (% zysku)'),
        ('trailing_stop_distance', '1.0', 'Dystans trailing stop (ATR)')
    ON CONFLICT (config_key) DO NOTHING;

    -- Konfiguracja wskaźników technicznych
    CREATE TABLE IF NOT EXISTS indicator_config (
        id SERIAL PRIMARY KEY,
        indicator_name VARCHAR(30) NOT NULL,
        param_name VARCHAR(30) NOT NULL,
        param_value DECIMAL(10,4) NOT NULL,
        description TEXT,
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(indicator_name, param_name)
    );

    -- Domyślne wartości wskaźników
    INSERT INTO indicator_config (indicator_name, param_name, param_value, description) VALUES
        -- RSI
        ('rsi', 'period', 14, 'Okres RSI'),
        ('rsi', 'oversold', 30, 'Poziom wyprzedania'),
        ('rsi', 'overbought', 70, 'Poziom wykupienia'),
        ('rsi', 'extreme_oversold', 20, 'Ekstremalny poziom wyprzedania'),
        ('rsi', 'extreme_overbought', 80, 'Ekstremalny poziom wykupienia'),
        -- MACD
        ('macd', 'fast_period', 12, 'Szybka EMA'),
        ('macd', 'slow_period', 26, 'Wolna EMA'),
        ('macd', 'signal_period', 9, 'Linia sygnału'),
        -- EMA
        ('ema', 'short', 9, 'Krótka EMA'),
        ('ema', 'medium', 21, 'Średnia EMA'),
        ('ema', 'long', 50, 'Długa EMA'),
        ('ema', 'trend', 200, 'EMA trendu'),
        -- Bollinger Bands
        ('bollinger', 'period', 20, 'Okres BB'),
        ('bollinger', 'std_dev', 2, 'Odchylenie standardowe'),
        -- ATR
        ('atr', 'period', 14, 'Okres ATR'),
        -- Volume
        ('volume', 'avg_period', 20, 'Okres średniej wolumenu'),
        ('volume', 'spike_multiplier', 1.5, 'Mnożnik dla spike wolumenu')
    ON CONFLICT (indicator_name, param_name) DO NOTHING;

    -- Wskaźniki rynkowe (OHLCV + obliczone wskaźniki)
    CREATE TABLE IF NOT EXISTS market_indicators (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        timeframe VARCHAR(10) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,

        -- OHLCV
        open DECIMAL(20,8),
        high DECIMAL(20,8),
        low DECIMAL(20,8),
        close DECIMAL(20,8),
        volume DECIMAL(20,8),

        -- RSI
        rsi_14 DECIMAL(10,4),

        -- MACD
        macd_line DECIMAL(20,8),
        macd_signal DECIMAL(20,8),
        macd_histogram DECIMAL(20,8),

        -- EMA
        ema_9 DECIMAL(20,8),
        ema_21 DECIMAL(20,8),
        ema_50 DECIMAL(20,8),
        ema_200 DECIMAL(20,8),

        -- Bollinger Bands
        bb_upper DECIMAL(20,8),
        bb_middle DECIMAL(20,8),
        bb_lower DECIMAL(20,8),
        bb_width DECIMAL(10,4),

        -- ATR
        atr_14 DECIMAL(20,8),

        -- Funding rate (tylko futures)
        funding_rate DECIMAL(10,6),

        -- Volume analysis
        volume_sma_20 DECIMAL(20,8),
        volume_ratio DECIMAL(10,4),

        created_at TIMESTAMPTZ DEFAULT NOW(),

        UNIQUE(symbol, timeframe, timestamp)
    );

    CREATE INDEX IF NOT EXISTS idx_indicators_symbol_tf_ts
        ON market_indicators(symbol, timeframe, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_indicators_timestamp
        ON market_indicators(timestamp DESC);

    -- Poziomy liquidity (wsparcia/oporu)
    CREATE TABLE IF NOT EXISTS market_liquidity_levels (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        level_type VARCHAR(20) NOT NULL CHECK (level_type IN ('support', 'resistance', 'liquidation')),
        price DECIMAL(20,8) NOT NULL,
        strength DECIMAL(10,4) DEFAULT 1.0,
        timeframe VARCHAR(20),
        source VARCHAR(50),
        valid_from TIMESTAMPTZ DEFAULT NOW(),
        valid_until TIMESTAMPTZ,
        touched_count INT DEFAULT 0,
        last_touched TIMESTAMPTZ,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        notes TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_liquidity_symbol_active
        ON market_liquidity_levels(symbol, is_active, price);

    -- Sygnały tradingowe
    CREATE TABLE IF NOT EXISTS trading_signals (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        signal_type VARCHAR(20) NOT NULL CHECK (signal_type IN ('long', 'short', 'close_long', 'close_short', 'hold')),

        -- Scoring
        score INT NOT NULL,
        confidence DECIMAL(5,4) NOT NULL,

        -- Ceny
        entry_price DECIMAL(20,8),
        stop_loss DECIMAL(20,8),
        take_profit DECIMAL(20,8),

        -- Kontekst
        reasons JSONB,
        indicators_snapshot JSONB,

        -- LLM analysis (opcjonalne)
        llm_analysis TEXT,
        llm_score INT,

        -- Status
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'expired', 'cancelled', 'rejected')),
        executed_at TIMESTAMPTZ,
        expired_at TIMESTAMPTZ,

        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_signals_symbol_status
        ON trading_signals(symbol, status, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_signals_created
        ON trading_signals(created_at DESC);

    -- Zlecenia
    CREATE TABLE IF NOT EXISTS trading_orders (
        id SERIAL PRIMARY KEY,
        signal_id INT REFERENCES trading_signals(id),

        -- Identyfikatory zewnętrzne
        exchange_order_id VARCHAR(100),
        client_order_id VARCHAR(100),

        -- Podstawowe info
        symbol VARCHAR(20) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
        order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit')),

        -- Ilości
        quantity DECIMAL(20,8) NOT NULL,
        filled_quantity DECIMAL(20,8) DEFAULT 0,

        -- Ceny
        price DECIMAL(20,8),
        stop_price DECIMAL(20,8),
        avg_fill_price DECIMAL(20,8),

        -- Leverage
        leverage INT DEFAULT 1,

        -- Status
        status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'partial', 'filled', 'cancelled', 'rejected', 'expired')),

        -- Paper trading flag
        is_paper BOOLEAN DEFAULT TRUE,

        -- Timestamps
        submitted_at TIMESTAMPTZ,
        filled_at TIMESTAMPTZ,
        cancelled_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW(),

        -- Error handling
        error_message TEXT,
        retry_count INT DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_orders_symbol_status
        ON trading_orders(symbol, status);
    CREATE INDEX IF NOT EXISTS idx_orders_exchange_id
        ON trading_orders(exchange_order_id);

    -- Aktywne pozycje
    CREATE TABLE IF NOT EXISTS trading_positions (
        id SERIAL PRIMARY KEY,
        signal_id INT REFERENCES trading_signals(id),
        entry_order_id INT REFERENCES trading_orders(id),

        -- Identyfikatory
        symbol VARCHAR(20) NOT NULL,
        side VARCHAR(10) NOT NULL CHECK (side IN ('long', 'short')),

        -- Rozmiar
        quantity DECIMAL(20,8) NOT NULL,
        entry_price DECIMAL(20,8) NOT NULL,
        leverage INT DEFAULT 1,

        -- Risk management
        stop_loss DECIMAL(20,8),
        take_profit DECIMAL(20,8),
        trailing_stop_distance DECIMAL(20,8),
        trailing_stop_price DECIMAL(20,8),

        -- P&L tracking
        current_price DECIMAL(20,8),
        unrealized_pnl DECIMAL(20,8),
        unrealized_pnl_percent DECIMAL(10,4),
        highest_pnl DECIMAL(20,8) DEFAULT 0,
        lowest_pnl DECIMAL(20,8) DEFAULT 0,

        -- Margin
        margin_used DECIMAL(20,8),
        liquidation_price DECIMAL(20,8),

        -- Status
        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closing', 'closed')),
        is_paper BOOLEAN DEFAULT TRUE,

        -- Timestamps
        opened_at TIMESTAMPTZ DEFAULT NOW(),
        last_updated TIMESTAMPTZ DEFAULT NOW(),
        closed_at TIMESTAMPTZ
    );

    CREATE INDEX IF NOT EXISTS idx_positions_symbol_status
        ON trading_positions(symbol, status);
    CREATE INDEX IF NOT EXISTS idx_positions_open
        ON trading_positions(status) WHERE status = 'open';

    -- Historia pozycji (zamknięte)
    CREATE TABLE IF NOT EXISTS trading_position_history (
        id SERIAL PRIMARY KEY,
        position_id INT,
        signal_id INT,

        -- Podstawowe info
        symbol VARCHAR(20) NOT NULL,
        side VARCHAR(10) NOT NULL,
        quantity DECIMAL(20,8) NOT NULL,
        leverage INT,

        -- Ceny
        entry_price DECIMAL(20,8) NOT NULL,
        exit_price DECIMAL(20,8) NOT NULL,

        -- P&L
        realized_pnl DECIMAL(20,8) NOT NULL,
        realized_pnl_percent DECIMAL(10,4) NOT NULL,
        fees DECIMAL(20,8) DEFAULT 0,
        net_pnl DECIMAL(20,8),

        -- Risk management results
        stop_loss_hit BOOLEAN DEFAULT FALSE,
        take_profit_hit BOOLEAN DEFAULT FALSE,
        trailing_stop_hit BOOLEAN DEFAULT FALSE,
        manual_close BOOLEAN DEFAULT FALSE,

        -- Analysis
        max_drawdown_percent DECIMAL(10,4),
        max_profit_percent DECIMAL(10,4),
        hold_duration_minutes INT,

        -- Context
        entry_reasons JSONB,
        exit_reason TEXT,

        -- Paper flag
        is_paper BOOLEAN DEFAULT TRUE,

        -- Timestamps
        opened_at TIMESTAMPTZ NOT NULL,
        closed_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_position_history_symbol
        ON trading_position_history(symbol, closed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_position_history_pnl
        ON trading_position_history(realized_pnl_percent);

    -- Metryki on-chain (Glassnode)
    CREATE TABLE IF NOT EXISTS onchain_metrics (
        id SERIAL PRIMARY KEY,
        metric_name VARCHAR(50) NOT NULL,
        asset VARCHAR(10) NOT NULL DEFAULT 'BTC',
        value DECIMAL(30,8) NOT NULL,
        timestamp TIMESTAMPTZ NOT NULL,
        source VARCHAR(30) DEFAULT 'glassnode',
        created_at TIMESTAMPTZ DEFAULT NOW(),

        UNIQUE(metric_name, asset, timestamp)
    );

    CREATE INDEX IF NOT EXISTS idx_onchain_metric_ts
        ON onchain_metrics(metric_name, asset, timestamp DESC);

    -- Embeddingi wiedzy tradingowej
    CREATE TABLE IF NOT EXISTS knowledge_embeddings (
        id SERIAL PRIMARY KEY,
        source_type VARCHAR(30) NOT NULL,
        source_id VARCHAR(100),
        source_url TEXT,

        chunk_index INT NOT NULL,
        chunk_text TEXT NOT NULL,
        embedding vector(1024),

        -- Metadata
        title TEXT,
        author TEXT,
        tags TEXT[],
        relevance_score DECIMAL(5,4),

        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_knowledge_embedding
        ON knowledge_embeddings USING ivfflat (embedding vector_cosine_ops);
    CREATE INDEX IF NOT EXISTS idx_knowledge_source
        ON knowledge_embeddings(source_type, source_id);
    CREATE INDEX IF NOT EXISTS idx_knowledge_tags
        ON knowledge_embeddings USING GIN (tags);

    -- Audit log
    CREATE TABLE IF NOT EXISTS trading_audit_log (
        id SERIAL PRIMARY KEY,
        event_type VARCHAR(50) NOT NULL,
        event_category VARCHAR(30) NOT NULL,

        -- Related entities
        symbol VARCHAR(20),
        position_id INT,
        order_id INT,
        signal_id INT,

        -- Event details
        details JSONB,

        -- Context
        triggered_by VARCHAR(50),
        ip_address VARCHAR(45),

        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_audit_event
        ON trading_audit_log(event_type, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_audit_symbol
        ON trading_audit_log(symbol, created_at DESC);

    -- Dzienny snapshot konta
    CREATE TABLE IF NOT EXISTS account_snapshots (
        id SERIAL PRIMARY KEY,
        snapshot_date DATE NOT NULL UNIQUE,

        -- Balances
        total_balance DECIMAL(20,8) NOT NULL,
        available_balance DECIMAL(20,8),
        margin_used DECIMAL(20,8),

        -- Daily P&L
        daily_pnl DECIMAL(20,8),
        daily_pnl_percent DECIMAL(10,4),

        -- Statistics
        open_positions_count INT DEFAULT 0,
        trades_count INT DEFAULT 0,
        win_count INT DEFAULT 0,
        loss_count INT DEFAULT 0,

        -- Risk metrics
        max_drawdown_percent DECIMAL(10,4),

        is_paper BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    -- =============================================
    -- VIEWS
    -- =============================================

    -- Widok aktywnych pozycji z P&L
    CREATE OR REPLACE VIEW v_active_positions AS
    SELECT
        p.*,
        s.signal_type,
        s.confidence as signal_confidence,
        s.reasons as signal_reasons
    FROM trading_positions p
    LEFT JOIN trading_signals s ON p.signal_id = s.id
    WHERE p.status = 'open';

    -- Widok statystyk tradingu
    CREATE OR REPLACE VIEW v_trading_stats AS
    SELECT
        symbol,
        COUNT(*) as total_trades,
        SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
        SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
        ROUND(100.0 * SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as win_rate,
        SUM(realized_pnl) as total_pnl,
        AVG(realized_pnl) as avg_pnl,
        AVG(CASE WHEN realized_pnl > 0 THEN realized_pnl END) as avg_win,
        AVG(CASE WHEN realized_pnl < 0 THEN realized_pnl END) as avg_loss,
        MAX(realized_pnl) as best_trade,
        MIN(realized_pnl) as worst_trade,
        AVG(hold_duration_minutes) as avg_hold_minutes
    FROM trading_position_history
    GROUP BY symbol;

    -- Widok ostatnich sygnałów
    CREATE OR REPLACE VIEW v_recent_signals AS
    SELECT
        s.*,
        CASE
            WHEN p.id IS NOT NULL THEN 'position_opened'
            WHEN s.status = 'expired' THEN 'expired'
            ELSE s.status
        END as outcome
    FROM trading_signals s
    LEFT JOIN trading_positions p ON s.id = p.signal_id
    WHERE s.created_at > NOW() - INTERVAL '24 hours'
    ORDER BY s.created_at DESC;

EOSQL

echo "Trading Agent schema created successfully"
