"""
Trading Signal Engine

Generuje sygnaly tradingowe na podstawie wskaznikow technicznych
i poziomow liquidity.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import json

from config import config
from .indicators import IndicatorValues


class SignalType(Enum):
    LONG = "long"
    SHORT = "short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"


@dataclass
class Signal:
    """Reprezentacja sygnalu tradingowego"""
    type: SignalType
    symbol: str
    score: int = 0
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)

    # Ceny
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # Dodatkowe info
    indicators_snapshot: Optional[Dict[str, Any]] = None
    llm_analysis: Optional[str] = None
    llm_score: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "symbol": self.symbol,
            "score": self.score,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class LiquidityLevel:
    """Poziom liquidity (wsparcie/opor)"""
    price: float
    level_type: str  # 'support' lub 'resistance'
    strength: float = 1.0
    timeframe: Optional[str] = None


class SignalEngine:
    """
    Silnik generowania sygnalow tradingowych

    Uzywa systemu punktowego do oceny warunkow wejscia/wyjscia:
    - RSI extreme: +3 pkt
    - RSI oversold/overbought: +2 pkt
    - MACD crossover: +2 pkt
    - Blisko liquidity level: +2 pkt
    - BB/EMA/Volume/Funding: +1 pkt kazdy

    Prog wejscia: suma >= min_score (domyslnie 5)
    """

    def __init__(self):
        self.cfg = config.indicators
        self.signal_cfg = config.signals
        self.risk_cfg = config.risk

        # Progi RSI
        self.rsi_oversold = self.cfg.rsi.oversold
        self.rsi_overbought = self.cfg.rsi.overbought
        self.rsi_extreme_oversold = self.cfg.rsi.extreme_oversold
        self.rsi_extreme_overbought = self.cfg.rsi.extreme_overbought

        # Progi sygnalu
        self.min_score = self.signal_cfg.min_score
        self.min_confidence = self.signal_cfg.min_confidence

        # ATR multipliers
        self.atr_sl_mult = self.cfg.atr.sl_multiplier
        self.atr_tp_mult = self.cfg.atr.tp_multiplier

    def evaluate_long(self, ind: IndicatorValues,
                      levels: List[LiquidityLevel]) -> tuple[int, List[str]]:
        """
        Ocena warunkow dla pozycji LONG

        Returns:
            (score, reasons) - punkty i lista powodow
        """
        score = 0
        reasons = []

        # RSI
        if ind.rsi_14 is not None:
            if ind.rsi_14 < self.rsi_extreme_oversold:
                score += 3
                reasons.append(f"RSI extreme oversold: {ind.rsi_14:.1f}")
            elif ind.rsi_14 < self.rsi_oversold:
                score += 2
                reasons.append(f"RSI oversold: {ind.rsi_14:.1f}")

        # MACD crossover (bullish)
        if ind.macd_histogram is not None and ind.macd_histogram_prev is not None:
            if ind.macd_histogram > 0 and ind.macd_histogram_prev <= 0:
                score += 2
                reasons.append("MACD bullish crossover")

        # Cena ponizej dolnej wstegi Bollingera
        if ind.close and ind.bb_lower:
            if ind.close < ind.bb_lower:
                score += 1
                reasons.append(f"Price below BB lower ({ind.close:.2f} < {ind.bb_lower:.2f})")

        # Cena powyzej EMA 200 (uptrend)
        if ind.close and ind.ema_200:
            if ind.close > ind.ema_200:
                score += 1
                reasons.append("Above EMA 200 (uptrend)")

        # EMA momentum (9 > 21)
        if ind.ema_9 and ind.ema_21:
            if ind.ema_9 > ind.ema_21:
                score += 1
                reasons.append("EMA 9 > EMA 21 (momentum)")

        # Volume spike
        if ind.volume_ratio and ind.volume_ratio > 1.5:
            score += 1
            reasons.append(f"Volume spike: {ind.volume_ratio:.1f}x")

        # Negative funding (shorts placa)
        if ind.funding_rate is not None and ind.funding_rate < -0.0001:
            score += 1
            reasons.append(f"Negative funding: {ind.funding_rate:.4%}")

        # Blisko poziomu wsparcia
        if ind.close:
            for level in levels:
                if level.level_type == "support":
                    distance_pct = abs(ind.close - level.price) / ind.close * 100
                    if distance_pct < 1.0:  # W granicach 1%
                        bonus = int(level.strength * 2)
                        score += bonus
                        reasons.append(f"Near support {level.price:.2f} ({distance_pct:.2f}%)")
                        break

        return score, reasons

    def evaluate_short(self, ind: IndicatorValues,
                       levels: List[LiquidityLevel]) -> tuple[int, List[str]]:
        """
        Ocena warunkow dla pozycji SHORT

        Returns:
            (score, reasons) - punkty i lista powodow
        """
        score = 0
        reasons = []

        # RSI
        if ind.rsi_14 is not None:
            if ind.rsi_14 > self.rsi_extreme_overbought:
                score += 3
                reasons.append(f"RSI extreme overbought: {ind.rsi_14:.1f}")
            elif ind.rsi_14 > self.rsi_overbought:
                score += 2
                reasons.append(f"RSI overbought: {ind.rsi_14:.1f}")

        # MACD crossover (bearish)
        if ind.macd_histogram is not None and ind.macd_histogram_prev is not None:
            if ind.macd_histogram < 0 and ind.macd_histogram_prev >= 0:
                score += 2
                reasons.append("MACD bearish crossover")

        # Cena powyzej gornej wstegi Bollingera
        if ind.close and ind.bb_upper:
            if ind.close > ind.bb_upper:
                score += 1
                reasons.append(f"Price above BB upper ({ind.close:.2f} > {ind.bb_upper:.2f})")

        # Cena ponizej EMA 200 (downtrend)
        if ind.close and ind.ema_200:
            if ind.close < ind.ema_200:
                score += 1
                reasons.append("Below EMA 200 (downtrend)")

        # EMA momentum (9 < 21)
        if ind.ema_9 and ind.ema_21:
            if ind.ema_9 < ind.ema_21:
                score += 1
                reasons.append("EMA 9 < EMA 21 (momentum)")

        # Volume spike
        if ind.volume_ratio and ind.volume_ratio > 1.5:
            score += 1
            reasons.append(f"Volume spike: {ind.volume_ratio:.1f}x")

        # High positive funding (longs placa)
        if ind.funding_rate is not None and ind.funding_rate > 0.0003:
            score += 1
            reasons.append(f"High positive funding: {ind.funding_rate:.4%}")

        # Blisko poziomu oporu
        if ind.close:
            for level in levels:
                if level.level_type == "resistance":
                    distance_pct = abs(ind.close - level.price) / ind.close * 100
                    if distance_pct < 1.0:
                        bonus = int(level.strength * 2)
                        score += bonus
                        reasons.append(f"Near resistance {level.price:.2f} ({distance_pct:.2f}%)")
                        break

        return score, reasons

    def evaluate_exit_long(self, ind: IndicatorValues,
                           entry_price: float,
                           levels: List[LiquidityLevel]) -> Optional[Signal]:
        """
        Sprawdz warunki wyjscia z pozycji LONG

        Returns:
            Signal CLOSE_LONG lub None
        """
        reasons = []
        confidence = 0.0

        # RSI overbought - take profit
        if ind.rsi_14 is not None:
            if ind.rsi_14 > self.rsi_extreme_overbought:
                reasons.append(f"RSI > {self.rsi_extreme_overbought} - full take profit")
                confidence = 0.9
            elif ind.rsi_14 > self.rsi_overbought:
                reasons.append(f"RSI > {self.rsi_overbought} - partial take profit")
                confidence = 0.6

        # MACD bearish crossover
        if ind.macd_histogram is not None and ind.macd_histogram_prev is not None:
            if ind.macd_histogram < 0 and ind.macd_histogram_prev >= 0:
                reasons.append("MACD bearish crossover")
                confidence = max(confidence, 0.7)

        # Blisko resistance
        if ind.close:
            for level in levels:
                if level.level_type == "resistance":
                    distance_pct = abs(ind.close - level.price) / ind.close * 100
                    if distance_pct < 0.5:
                        reasons.append(f"At resistance {level.price:.2f}")
                        confidence = max(confidence, 0.65)
                        break

        if reasons:
            return Signal(
                type=SignalType.CLOSE_LONG,
                symbol="",
                confidence=confidence,
                reasons=reasons
            )

        return None

    def evaluate_exit_short(self, ind: IndicatorValues,
                            entry_price: float,
                            levels: List[LiquidityLevel]) -> Optional[Signal]:
        """
        Sprawdz warunki wyjscia z pozycji SHORT

        Returns:
            Signal CLOSE_SHORT lub None
        """
        reasons = []
        confidence = 0.0

        # RSI oversold - take profit
        if ind.rsi_14 is not None:
            if ind.rsi_14 < self.rsi_extreme_oversold:
                reasons.append(f"RSI < {self.rsi_extreme_oversold} - full take profit")
                confidence = 0.9
            elif ind.rsi_14 < self.rsi_oversold:
                reasons.append(f"RSI < {self.rsi_oversold} - partial take profit")
                confidence = 0.6

        # MACD bullish crossover
        if ind.macd_histogram is not None and ind.macd_histogram_prev is not None:
            if ind.macd_histogram > 0 and ind.macd_histogram_prev <= 0:
                reasons.append("MACD bullish crossover")
                confidence = max(confidence, 0.7)

        # Blisko support
        if ind.close:
            for level in levels:
                if level.level_type == "support":
                    distance_pct = abs(ind.close - level.price) / ind.close * 100
                    if distance_pct < 0.5:
                        reasons.append(f"At support {level.price:.2f}")
                        confidence = max(confidence, 0.65)
                        break

        if reasons:
            return Signal(
                type=SignalType.CLOSE_SHORT,
                symbol="",
                confidence=confidence,
                reasons=reasons
            )

        return None

    def calculate_sl_tp(self, entry_price: float, atr: float,
                        side: str) -> tuple[float, float]:
        """
        Oblicz Stop Loss i Take Profit na podstawie ATR

        Args:
            entry_price: cena wejscia
            atr: Average True Range
            side: 'long' lub 'short'

        Returns:
            (stop_loss, take_profit)
        """
        sl_distance = atr * self.atr_sl_mult
        tp_distance = atr * self.atr_tp_mult

        if side == "long":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:  # short
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        return stop_loss, take_profit

    def generate_signal(self, symbol: str,
                        indicators: IndicatorValues,
                        liquidity_levels: List[LiquidityLevel],
                        current_position: Optional[str] = None) -> Signal:
        """
        Generuj sygnal tradingowy

        Args:
            symbol: symbol instrumentu (np. BTC_USDT)
            indicators: obliczone wskazniki
            liquidity_levels: poziomy wsparcia/oporu
            current_position: aktualna pozycja ('long', 'short', None)

        Returns:
            Signal z typem, confidence i powodami
        """
        close = indicators.close or 0
        atr = indicators.atr_14 or (close * 0.02)  # fallback 2%

        # Jesli mamy pozycje - sprawdz warunki wyjscia
        if current_position == "long":
            exit_signal = self.evaluate_exit_long(indicators, close, liquidity_levels)
            if exit_signal:
                exit_signal.symbol = symbol
                exit_signal.indicators_snapshot = indicators.to_dict()
                return exit_signal

        elif current_position == "short":
            exit_signal = self.evaluate_exit_short(indicators, close, liquidity_levels)
            if exit_signal:
                exit_signal.symbol = symbol
                exit_signal.indicators_snapshot = indicators.to_dict()
                return exit_signal

        # Ocena nowych pozycji
        long_score, long_reasons = self.evaluate_long(indicators, liquidity_levels)
        short_score, short_reasons = self.evaluate_short(indicators, liquidity_levels)

        # Wybierz silniejszy sygnal
        if long_score >= self.min_score and long_score > short_score:
            sl, tp = self.calculate_sl_tp(close, atr, "long")
            confidence = min(long_score / 10.0, 1.0)

            return Signal(
                type=SignalType.LONG,
                symbol=symbol,
                score=long_score,
                confidence=confidence,
                reasons=long_reasons,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                indicators_snapshot=indicators.to_dict()
            )

        if short_score >= self.min_score and short_score > long_score:
            sl, tp = self.calculate_sl_tp(close, atr, "short")
            confidence = min(short_score / 10.0, 1.0)

            return Signal(
                type=SignalType.SHORT,
                symbol=symbol,
                score=short_score,
                confidence=confidence,
                reasons=short_reasons,
                entry_price=close,
                stop_loss=sl,
                take_profit=tp,
                indicators_snapshot=indicators.to_dict()
            )

        # Brak sygnalu
        return Signal(
            type=SignalType.HOLD,
            symbol=symbol,
            score=max(long_score, short_score),
            confidence=0,
            reasons=[f"No clear signal (long={long_score}, short={short_score}, min={self.min_score})"]
        )

    def should_execute(self, signal: Signal) -> bool:
        """
        Sprawdz czy sygnal powinien byc wykonany

        Returns:
            True jesli sygnal spelnia minimalne wymagania
        """
        if signal.type == SignalType.HOLD:
            return False

        if signal.type in (SignalType.CLOSE_LONG, SignalType.CLOSE_SHORT):
            return signal.confidence >= 0.5

        return (
            signal.score >= self.min_score and
            signal.confidence >= self.min_confidence
        )
