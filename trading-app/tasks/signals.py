"""
Signal Generation Task

Generuje sygnały tradingowe na podstawie wskaźników technicznych,
poziomów liquidity i analizy LLM.
"""
import logging
from typing import List, Optional

from config import config
from core.database import Database
from core.gate_api import GateIOClient
from core.ollama_client import OllamaClient
from core.indicators import TechnicalIndicators, IndicatorValues
from core.signal_engine import SignalEngine, Signal, SignalType, LiquidityLevel

logger = logging.getLogger(__name__)


class SignalGenerator:
    """Generator sygnałów tradingowych"""

    def __init__(self):
        self.db = Database()
        self.gate = GateIOClient()
        self.ollama = OllamaClient()
        self.indicators = TechnicalIndicators()
        self.engine = SignalEngine()
        self.symbols = config.symbols
        self.timeframes = config.signals.timeframes

    def get_market_data(self, symbol: str, timeframe: str = "15m",
                        limit: int = 200):
        """Pobierz dane rynkowe z GATE.io"""
        try:
            df = self.gate.get_candlesticks(symbol, timeframe, limit)
            return df
        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            return None

    def get_liquidity_levels(self, symbol: str) -> List[LiquidityLevel]:
        """Pobierz poziomy liquidity z bazy"""
        try:
            levels = self.db.get_active_levels(symbol)
            return [
                LiquidityLevel(
                    price=float(l["price"]),
                    level_type=l["level_type"],
                    strength=float(l.get("strength", 1.0)),
                    timeframe=l.get("timeframe")
                )
                for l in levels
            ]
        except Exception as e:
            logger.error(f"Failed to get liquidity levels for {symbol}: {e}")
            return []

    def get_current_position(self, symbol: str) -> Optional[str]:
        """Sprawdź aktualną pozycję dla symbolu"""
        try:
            positions = self.db.get_open_positions(symbol)
            if positions:
                return positions[0]["side"]
            return None
        except Exception as e:
            logger.error(f"Failed to get position for {symbol}: {e}")
            return None

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Pobierz funding rate z GATE.io"""
        try:
            return self.gate.get_funding_rate(symbol)
        except Exception as e:
            logger.warning(f"Failed to get funding rate for {symbol}: {e}")
            return None

    def enhance_with_llm(self, signal: Signal,
                         indicators: IndicatorValues) -> Signal:
        """Rozszerz sygnał o analizę LLM"""
        if signal.confidence < 0.5:
            return signal

        if signal.type == SignalType.HOLD:
            return signal

        try:
            # Semantic search for relevant knowledge
            query = f"{signal.symbol} {signal.type.value} trading"
            embedding = self.ollama.embed(query)
            knowledge = self.db.semantic_search(embedding, limit=3)
            knowledge_texts = [k["chunk_text"] for k in knowledge]

            # LLM analysis
            analysis = self.ollama.analyze_signal(
                signal.to_dict(),
                indicators.to_dict(),
                knowledge_texts
            )

            signal.llm_analysis = analysis.get("reasoning", "")
            signal.llm_score = analysis.get("score", 0)

            # Adjust confidence based on LLM score
            if analysis.get("recommendation") == "execute":
                signal.confidence = min(signal.confidence * 1.2, 1.0)
            elif analysis.get("recommendation") == "reject":
                signal.confidence = signal.confidence * 0.5

            logger.info(f"LLM analysis for {signal.symbol}: score={signal.llm_score}, "
                       f"recommendation={analysis.get('recommendation')}")

        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")

        return signal

    def process_symbol(self, symbol: str) -> Optional[Signal]:
        """Przetwórz jeden symbol i wygeneruj sygnał"""
        logger.info(f"Processing signal for {symbol}")

        # Get market data
        df = self.get_market_data(symbol, "15m", 200)
        if df is None or df.empty:
            logger.warning(f"No market data for {symbol}")
            return None

        # Calculate indicators
        df = self.indicators.calculate_all(df)

        # Get funding rate
        funding_rate = self.get_funding_rate(symbol)

        # Get latest indicator values
        ind_values = self.indicators.get_latest_values(df, funding_rate)

        # Get liquidity levels
        levels = self.get_liquidity_levels(symbol)

        # Get current position
        current_position = self.get_current_position(symbol)

        # Generate signal
        signal = self.engine.generate_signal(
            symbol=symbol,
            indicators=ind_values,
            liquidity_levels=levels,
            current_position=current_position
        )

        # Enhance with LLM if signal is actionable
        if signal.type != SignalType.HOLD:
            signal = self.enhance_with_llm(signal, ind_values)

        return signal

    def save_signal(self, signal: Signal) -> Optional[int]:
        """Zapisz sygnał do bazy danych"""
        if signal.type == SignalType.HOLD:
            return None

        try:
            signal_id = self.db.save_signal(signal)
            logger.info(f"Saved signal {signal_id}: {signal.type.value} {signal.symbol} "
                       f"(score={signal.score}, confidence={signal.confidence:.2f})")
            return signal_id
        except Exception as e:
            logger.error(f"Failed to save signal: {e}")
            return None

    def should_execute(self, signal: Signal) -> bool:
        """Sprawdź czy sygnał powinien być wykonany"""
        # Check basic conditions
        if not self.engine.should_execute(signal):
            return False

        # Check if trading is enabled
        if not self.db.is_trading_enabled():
            logger.info("Trading is disabled")
            return False

        # Check max open positions
        open_positions = self.db.get_open_positions()
        if len(open_positions) >= config.risk.max_open_positions:
            logger.info("Max open positions reached")
            return False

        return True

    def execute_signal(self, signal: Signal) -> bool:
        """Wykonaj sygnał (otwórz/zamknij pozycję)"""
        is_paper = self.db.is_paper_trading()

        logger.info(f"Executing signal: {signal.type.value} {signal.symbol} "
                   f"(paper={is_paper})")

        try:
            if signal.type in (SignalType.LONG, SignalType.SHORT):
                # Calculate position size
                atr = signal.indicators_snapshot.get("atr_14", 0) if signal.indicators_snapshot else 0
                sl_distance = atr * config.indicators.atr.sl_multiplier if atr else signal.entry_price * 0.02

                size = self.gate.calculate_position_size(
                    signal.symbol,
                    risk_percent=1.0,  # 1% risk per trade
                    stop_loss_distance=sl_distance
                )

                if is_paper:
                    # Paper trading - just save to database
                    position_id = self.db.create_position(
                        symbol=signal.symbol,
                        side=signal.type.value,
                        quantity=size,
                        entry_price=signal.entry_price,
                        leverage=config.risk.default_leverage,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit
                    )
                    logger.info(f"Paper position created: {position_id}")
                else:
                    # Live trading
                    order_size = size if signal.type == SignalType.LONG else -size
                    order = self.gate.create_order(
                        symbol=signal.symbol,
                        size=order_size
                    )
                    logger.info(f"Order placed: {order}")

                return True

            elif signal.type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
                # Close position
                positions = self.db.get_open_positions(signal.symbol)
                if positions:
                    pos = positions[0]
                    current_price = signal.indicators_snapshot.get("close", pos["entry_price"])

                    if is_paper:
                        self.db.close_position(
                            pos["id"],
                            exit_price=current_price,
                            exit_reason=", ".join(signal.reasons)
                        )
                    else:
                        self.gate.close_position(signal.symbol)

                    logger.info(f"Position closed for {signal.symbol}")
                    return True

        except Exception as e:
            logger.error(f"Failed to execute signal: {e}")
            return False

        return False

    def run(self):
        """Główna funkcja - przetwórz wszystkie symbole"""
        logger.info("Starting signal generation...")

        for symbol in self.symbols:
            try:
                signal = self.process_symbol(symbol)

                if signal is None:
                    continue

                # Log signal
                logger.info(f"Signal for {symbol}: {signal.type.value} "
                           f"(score={signal.score}, confidence={signal.confidence:.2f})")

                # Save actionable signals
                if signal.type != SignalType.HOLD:
                    self.save_signal(signal)

                    # Execute if conditions are met
                    if self.should_execute(signal):
                        self.execute_signal(signal)

                # Log audit
                self.db.log_event(
                    event_type="signal_generated",
                    category="signals",
                    symbol=symbol,
                    details=signal.to_dict(),
                    triggered_by="scheduler"
                )

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                continue

        logger.info("Signal generation completed")


# Task function for scheduler
def generate_signals():
    """Task function to generate trading signals"""
    generator = SignalGenerator()
    generator.run()


# For testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_signals()
