"""
Market Data Collection Task

Pobiera dane rynkowe z GATE.io i zapisuje do bazy danych.
"""
import logging
from datetime import datetime

from config import config
from core.database import Database
from core.gate_api import GateIOClient
from core.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class MarketDataCollector:
    """Kolektor danych rynkowych"""

    def __init__(self):
        self.db = Database()
        self.gate = GateIOClient()
        self.indicators = TechnicalIndicators()
        self.symbols = config.symbols
        self.timeframes = ["1m", "5m", "15m", "1h"]

    def collect_ohlcv(self, symbol: str, timeframe: str, limit: int = 100):
        """Pobierz OHLCV dla symbolu i timeframe"""
        try:
            df = self.gate.get_candlesticks(symbol, timeframe, limit)
            if df.empty:
                logger.warning(f"No data for {symbol} {timeframe}")
                return None

            # Calculate indicators
            df = self.indicators.calculate_all(df)

            # Save to database
            self.db.save_indicators(symbol, timeframe, df)

            logger.debug(f"Saved {len(df)} candles for {symbol} {timeframe}")
            return df

        except Exception as e:
            logger.error(f"Failed to collect {symbol} {timeframe}: {e}")
            return None

    def collect_funding_rate(self, symbol: str):
        """Pobierz funding rate"""
        try:
            rate = self.gate.get_funding_rate(symbol)
            logger.debug(f"Funding rate {symbol}: {rate:.6f}")
            return rate
        except Exception as e:
            logger.warning(f"Failed to get funding rate for {symbol}: {e}")
            return None

    def collect_ticker(self, symbol: str):
        """Pobierz ticker info"""
        try:
            ticker = self.gate.get_ticker(symbol)
            return {
                "last_price": float(ticker.get("last", 0)),
                "volume_24h": float(ticker.get("volume_24h", 0)),
                "high_24h": float(ticker.get("high_24h", 0)),
                "low_24h": float(ticker.get("low_24h", 0)),
                "change_24h": float(ticker.get("change_percentage", 0))
            }
        except Exception as e:
            logger.warning(f"Failed to get ticker for {symbol}: {e}")
            return None

    def run(self):
        """Główna funkcja - zbierz dane dla wszystkich symboli"""
        logger.info("Starting market data collection...")

        for symbol in self.symbols:
            # Collect for each timeframe
            for tf in self.timeframes:
                self.collect_ohlcv(symbol, tf)

            # Collect funding rate
            self.collect_funding_rate(symbol)

            # Log audit
            self.db.log_event(
                event_type="market_data_collected",
                category="market",
                symbol=symbol,
                triggered_by="scheduler"
            )

        logger.info("Market data collection completed")


def collect_market_data():
    """Task function for scheduler"""
    collector = MarketDataCollector()
    collector.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collect_market_data()
