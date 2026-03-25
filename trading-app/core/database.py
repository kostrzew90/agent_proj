"""
Database Client for PostgreSQL + pgvector

Obsługuje połączenie z bazą danych i operacje na tabelach tradingowych.
"""
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import pandas as pd

from config import config


class Database:
    """PostgreSQL database client"""

    def __init__(self):
        self.cfg = config.database
        self._conn = None

    @contextmanager
    def get_connection(self):
        """Context manager for database connection"""
        conn = psycopg2.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            user=self.cfg.user,
            password=self.cfg.password,
            database=self.cfg.database
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        """Context manager for database cursor"""
        with self.get_connection() as conn:
            cursor_factory = RealDictCursor if dict_cursor else None
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
            finally:
                cursor.close()

    # ==========================================
    # Config Operations
    # ==========================================

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT config_value FROM trading_risk_config WHERE config_key = %s",
                (key,)
            )
            row = cur.fetchone()
            if row:
                return row["config_value"]
            return default

    def set_config(self, key: str, value: Any, description: str = None):
        """Set configuration value"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO trading_risk_config (config_key, config_value, description, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (config_key) DO UPDATE SET
                    config_value = EXCLUDED.config_value,
                    updated_at = NOW()
            """, (key, str(value), description))

    def get_all_config(self) -> Dict[str, str]:
        """Get all configuration values"""
        with self.get_cursor() as cur:
            cur.execute("SELECT config_key, config_value FROM trading_risk_config")
            return {row["config_key"]: row["config_value"] for row in cur.fetchall()}

    def is_paper_trading(self) -> bool:
        """Check if paper trading mode is enabled"""
        return self.get_config("paper_trading_mode", "true").lower() == "true"

    def is_trading_enabled(self) -> bool:
        """Check if trading is enabled"""
        return self.get_config("trading_enabled", "false").lower() == "true"

    # ==========================================
    # Indicator Config
    # ==========================================

    def get_indicator_config(self, indicator: str) -> Dict[str, float]:
        """Get indicator configuration"""
        with self.get_cursor() as cur:
            cur.execute(
                "SELECT param_name, param_value FROM indicator_config WHERE indicator_name = %s",
                (indicator,)
            )
            return {row["param_name"]: float(row["param_value"]) for row in cur.fetchall()}

    # ==========================================
    # Market Indicators
    # ==========================================

    def save_indicators(self, symbol: str, timeframe: str,
                        data: pd.DataFrame):
        """Save market indicators to database"""
        if data.empty:
            return

        columns = [
            "symbol", "timeframe", "timestamp",
            "open", "high", "low", "close", "volume",
            "rsi_14", "macd_line", "macd_signal", "macd_histogram",
            "ema_9", "ema_21", "ema_50", "ema_200",
            "bb_upper", "bb_middle", "bb_lower", "bb_width",
            "atr_14", "volume_sma_20", "volume_ratio"
        ]

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                values = []
                for _, row in data.iterrows():
                    values.append((
                        symbol, timeframe, row.get("timestamp"),
                        row.get("open"), row.get("high"), row.get("low"),
                        row.get("close"), row.get("volume"),
                        row.get("rsi_14"), row.get("macd_line"),
                        row.get("macd_signal"), row.get("macd_histogram"),
                        row.get("ema_9"), row.get("ema_21"),
                        row.get("ema_50"), row.get("ema_200"),
                        row.get("bb_upper"), row.get("bb_middle"),
                        row.get("bb_lower"), row.get("bb_width"),
                        row.get("atr_14"), row.get("volume_sma_20"),
                        row.get("volume_ratio")
                    ))

                execute_values(cur, f"""
                    INSERT INTO market_indicators ({', '.join(columns)})
                    VALUES %s
                    ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE SET
                        close = EXCLUDED.close,
                        rsi_14 = EXCLUDED.rsi_14,
                        macd_histogram = EXCLUDED.macd_histogram,
                        updated_at = NOW()
                """, values)

    def get_latest_indicators(self, symbol: str, timeframe: str,
                              limit: int = 200) -> pd.DataFrame:
        """Get latest market indicators"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM market_indicators
                WHERE symbol = %s AND timeframe = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (symbol, timeframe, limit))

            rows = cur.fetchall()
            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            return df.sort_values("timestamp").reset_index(drop=True)

    # ==========================================
    # Liquidity Levels
    # ==========================================

    def save_liquidity_level(self, symbol: str, level_type: str,
                             price: float, strength: float = 1.0,
                             timeframe: str = None, source: str = None):
        """Save liquidity level"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO market_liquidity_levels
                (symbol, level_type, price, strength, timeframe, source)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (symbol, level_type, price, strength, timeframe, source))

    def get_active_levels(self, symbol: str) -> List[Dict]:
        """Get active liquidity levels for symbol"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM market_liquidity_levels
                WHERE symbol = %s AND is_active = TRUE
                ORDER BY price
            """, (symbol,))
            return list(cur.fetchall())

    def deactivate_old_levels(self, symbol: str, hours: int = 24):
        """Deactivate old liquidity levels"""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE market_liquidity_levels
                SET is_active = FALSE
                WHERE symbol = %s
                AND created_at < NOW() - INTERVAL '%s hours'
            """, (symbol, hours))

    # ==========================================
    # Trading Signals
    # ==========================================

    def save_signal(self, signal) -> int:
        """Save trading signal and return ID"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO trading_signals
                (symbol, signal_type, score, confidence, entry_price,
                 stop_loss, take_profit, reasons, indicators_snapshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                signal.symbol,
                signal.type.value,
                signal.score,
                signal.confidence,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                json.dumps(signal.reasons),
                json.dumps(signal.indicators_snapshot) if signal.indicators_snapshot else None
            ))
            return cur.fetchone()["id"]

    def get_pending_signals(self, symbol: str = None) -> List[Dict]:
        """Get pending signals"""
        with self.get_cursor() as cur:
            if symbol:
                cur.execute("""
                    SELECT * FROM trading_signals
                    WHERE status = 'pending' AND symbol = %s
                    ORDER BY created_at DESC
                """, (symbol,))
            else:
                cur.execute("""
                    SELECT * FROM trading_signals
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                """)
            return list(cur.fetchall())

    def update_signal_status(self, signal_id: int, status: str):
        """Update signal status"""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE trading_signals
                SET status = %s,
                    executed_at = CASE WHEN %s = 'executed' THEN NOW() ELSE executed_at END,
                    expired_at = CASE WHEN %s = 'expired' THEN NOW() ELSE expired_at END
                WHERE id = %s
            """, (status, status, status, signal_id))

    def get_recent_signals(self, hours: int = 24, limit: int = 50) -> List[Dict]:
        """Get recent signals"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT * FROM v_recent_signals
                LIMIT %s
            """, (limit,))
            return list(cur.fetchall())

    # ==========================================
    # Positions
    # ==========================================

    def create_position(self, symbol: str, side: str, quantity: float,
                        entry_price: float, signal_id: int = None,
                        leverage: int = 1, stop_loss: float = None,
                        take_profit: float = None) -> int:
        """Create new position"""
        is_paper = self.is_paper_trading()

        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO trading_positions
                (symbol, side, quantity, entry_price, signal_id, leverage,
                 stop_loss, take_profit, is_paper, current_price, unrealized_pnl)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0)
                RETURNING id
            """, (symbol, side, quantity, entry_price, signal_id, leverage,
                  stop_loss, take_profit, is_paper, entry_price))
            return cur.fetchone()["id"]

    def get_open_positions(self, symbol: str = None) -> List[Dict]:
        """Get open positions"""
        with self.get_cursor() as cur:
            if symbol:
                cur.execute("""
                    SELECT * FROM trading_positions
                    WHERE status = 'open' AND symbol = %s
                """, (symbol,))
            else:
                cur.execute("""
                    SELECT * FROM trading_positions
                    WHERE status = 'open'
                """)
            return list(cur.fetchall())

    def update_position_pnl(self, position_id: int, current_price: float,
                            unrealized_pnl: float, pnl_percent: float):
        """Update position P&L"""
        with self.get_cursor() as cur:
            cur.execute("""
                UPDATE trading_positions
                SET current_price = %s,
                    unrealized_pnl = %s,
                    unrealized_pnl_percent = %s,
                    highest_pnl = GREATEST(highest_pnl, %s),
                    lowest_pnl = LEAST(lowest_pnl, %s),
                    last_updated = NOW()
                WHERE id = %s
            """, (current_price, unrealized_pnl, pnl_percent,
                  unrealized_pnl, unrealized_pnl, position_id))

    def close_position(self, position_id: int, exit_price: float,
                       exit_reason: str):
        """Close position and move to history"""
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get position
                cur.execute("SELECT * FROM trading_positions WHERE id = %s", (position_id,))
                pos = cur.fetchone()
                if not pos:
                    return

                # Calculate P&L
                if pos["side"] == "long":
                    pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
                else:
                    pnl = (pos["entry_price"] - exit_price) * pos["quantity"]

                pnl_percent = (pnl / (pos["entry_price"] * pos["quantity"])) * 100

                # Calculate hold duration
                hold_minutes = int((datetime.now() - pos["opened_at"]).total_seconds() / 60)

                # Insert into history
                cur.execute("""
                    INSERT INTO trading_position_history
                    (position_id, signal_id, symbol, side, quantity, leverage,
                     entry_price, exit_price, realized_pnl, realized_pnl_percent,
                     net_pnl, exit_reason, hold_duration_minutes, is_paper,
                     opened_at, closed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    position_id, pos["signal_id"], pos["symbol"], pos["side"],
                    pos["quantity"], pos["leverage"], pos["entry_price"],
                    exit_price, pnl, pnl_percent, pnl, exit_reason,
                    hold_minutes, pos["is_paper"], pos["opened_at"]
                ))

                # Update position status
                cur.execute("""
                    UPDATE trading_positions
                    SET status = 'closed', closed_at = NOW()
                    WHERE id = %s
                """, (position_id,))

    def get_position_history(self, symbol: str = None,
                             limit: int = 100) -> List[Dict]:
        """Get position history"""
        with self.get_cursor() as cur:
            if symbol:
                cur.execute("""
                    SELECT * FROM trading_position_history
                    WHERE symbol = %s
                    ORDER BY closed_at DESC
                    LIMIT %s
                """, (symbol, limit))
            else:
                cur.execute("""
                    SELECT * FROM trading_position_history
                    ORDER BY closed_at DESC
                    LIMIT %s
                """, (limit,))
            return list(cur.fetchall())

    # ==========================================
    # Trading Stats
    # ==========================================

    def get_trading_stats(self, symbol: str = None) -> Dict:
        """Get trading statistics"""
        with self.get_cursor() as cur:
            if symbol:
                cur.execute("""
                    SELECT * FROM v_trading_stats WHERE symbol = %s
                """, (symbol,))
            else:
                cur.execute("SELECT * FROM v_trading_stats")

            rows = cur.fetchall()
            if not rows:
                return {}

            if symbol:
                return dict(rows[0])
            return {row["symbol"]: dict(row) for row in rows}

    # ==========================================
    # Audit Log
    # ==========================================

    def log_event(self, event_type: str, category: str,
                  details: Dict = None, symbol: str = None,
                  position_id: int = None, order_id: int = None,
                  signal_id: int = None, triggered_by: str = None):
        """Log audit event"""
        with self.get_cursor() as cur:
            cur.execute("""
                INSERT INTO trading_audit_log
                (event_type, event_category, symbol, position_id, order_id,
                 signal_id, details, triggered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                event_type, category, symbol, position_id, order_id,
                signal_id, json.dumps(details) if details else None, triggered_by
            ))

    # ==========================================
    # Knowledge Embeddings
    # ==========================================

    def semantic_search(self, embedding: List[float], limit: int = 5) -> List[Dict]:
        """Search knowledge base by embedding similarity"""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT id, source_type, source_id, chunk_text, title,
                       1 - (embedding <=> %s::vector) as similarity
                FROM knowledge_embeddings
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (embedding, embedding, limit))
            return list(cur.fetchall())
