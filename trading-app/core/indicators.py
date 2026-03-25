"""
Technical Indicators Calculator

Oblicza RSI, MACD, EMA, Bollinger Bands, ATR i inne wskazniki techniczne.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
from dataclasses import dataclass

from config import config


@dataclass
class IndicatorValues:
    """Container for all indicator values at a point in time"""
    # Price data
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0

    # RSI
    rsi_14: Optional[float] = None

    # MACD
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_histogram_prev: Optional[float] = None

    # EMA
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None

    # Bollinger Bands
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None

    # ATR
    atr_14: Optional[float] = None

    # Volume
    volume_sma_20: Optional[float] = None
    volume_ratio: Optional[float] = None

    # Funding
    funding_rate: Optional[float] = None

    def to_dict(self) -> Dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class TechnicalIndicators:
    """Kalkulator wskaznikow technicznych"""

    def __init__(self):
        self.cfg = config.indicators

    def rsi(self, closes: pd.Series, period: int = None) -> pd.Series:
        """
        Relative Strength Index

        RSI = 100 - (100 / (1 + RS))
        RS = Average Gain / Average Loss
        """
        period = period or self.cfg.rsi.period
        delta = closes.diff()

        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))

        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        # Unikaj dzielenia przez zero
        rs = avg_gain / avg_loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def macd(self, closes: pd.Series,
             fast: int = None,
             slow: int = None,
             signal: int = None) -> Dict[str, pd.Series]:
        """
        Moving Average Convergence Divergence

        MACD Line = EMA(fast) - EMA(slow)
        Signal Line = EMA(MACD Line)
        Histogram = MACD Line - Signal Line
        """
        fast = fast or self.cfg.macd.fast_period
        slow = slow or self.cfg.macd.slow_period
        signal = signal or self.cfg.macd.signal_period

        ema_fast = closes.ewm(span=fast, adjust=False).mean()
        ema_slow = closes.ewm(span=slow, adjust=False).mean()

        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        return {
            "macd_line": macd_line,
            "macd_signal": signal_line,
            "macd_histogram": histogram
        }

    def ema(self, closes: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average"""
        return closes.ewm(span=period, adjust=False).mean()

    def sma(self, values: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average"""
        return values.rolling(window=period).mean()

    def bollinger_bands(self, closes: pd.Series,
                        period: int = None,
                        std_dev: float = None) -> Dict[str, pd.Series]:
        """
        Bollinger Bands

        Middle = SMA(period)
        Upper = Middle + (std_dev * StdDev)
        Lower = Middle - (std_dev * StdDev)
        """
        period = period or self.cfg.bollinger.period
        std_dev = std_dev or self.cfg.bollinger.std_dev

        middle = closes.rolling(window=period).mean()
        std = closes.rolling(window=period).std()

        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        width = (upper - lower) / middle

        return {
            "bb_upper": upper,
            "bb_middle": middle,
            "bb_lower": lower,
            "bb_width": width
        }

    def atr(self, high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = None) -> pd.Series:
        """
        Average True Range

        TR = max(High - Low, |High - Close_prev|, |Low - Close_prev|)
        ATR = SMA(TR, period)
        """
        period = period or self.cfg.atr.period

        close_prev = close.shift(1)

        tr1 = high - low
        tr2 = abs(high - close_prev)
        tr3 = abs(low - close_prev)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        return tr.rolling(window=period).mean()

    def volume_analysis(self, volume: pd.Series, period: int = 20) -> Dict[str, pd.Series]:
        """Analiza wolumenu"""
        sma = volume.rolling(window=period).mean()
        ratio = volume / sma

        return {
            "volume_sma": sma,
            "volume_ratio": ratio
        }

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Oblicz wszystkie wskazniki dla DataFrame z kolumnami OHLCV

        Args:
            df: DataFrame z kolumnami: open, high, low, close, volume

        Returns:
            DataFrame z dodanymi kolumnami wskaznikow
        """
        result = df.copy()

        # RSI
        result["rsi_14"] = self.rsi(df["close"])

        # MACD
        macd = self.macd(df["close"])
        result["macd_line"] = macd["macd_line"]
        result["macd_signal"] = macd["macd_signal"]
        result["macd_histogram"] = macd["macd_histogram"]

        # EMA
        result["ema_9"] = self.ema(df["close"], self.cfg.ema.short)
        result["ema_21"] = self.ema(df["close"], self.cfg.ema.medium)
        result["ema_50"] = self.ema(df["close"], self.cfg.ema.long)
        result["ema_200"] = self.ema(df["close"], self.cfg.ema.trend)

        # Bollinger Bands
        bb = self.bollinger_bands(df["close"])
        result["bb_upper"] = bb["bb_upper"]
        result["bb_middle"] = bb["bb_middle"]
        result["bb_lower"] = bb["bb_lower"]
        result["bb_width"] = bb["bb_width"]

        # ATR
        result["atr_14"] = self.atr(df["high"], df["low"], df["close"])

        # Volume
        vol = self.volume_analysis(df["volume"])
        result["volume_sma_20"] = vol["volume_sma"]
        result["volume_ratio"] = vol["volume_ratio"]

        return result

    def get_latest_values(self, df: pd.DataFrame,
                          funding_rate: Optional[float] = None) -> IndicatorValues:
        """
        Pobierz najnowsze wartosci wskaznikow

        Args:
            df: DataFrame z obliczonymi wskaznikami
            funding_rate: opcjonalny funding rate z gieldy

        Returns:
            IndicatorValues z ostatnimi wartosciami
        """
        if df.empty:
            return IndicatorValues()

        # Oblicz wskazniki jesli nie ma
        if "rsi_14" not in df.columns:
            df = self.calculate_all(df)

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]

        return IndicatorValues(
            open=float(last.get("open", 0)),
            high=float(last.get("high", 0)),
            low=float(last.get("low", 0)),
            close=float(last.get("close", 0)),
            volume=float(last.get("volume", 0)),

            rsi_14=float(last.get("rsi_14")) if pd.notna(last.get("rsi_14")) else None,

            macd_line=float(last.get("macd_line")) if pd.notna(last.get("macd_line")) else None,
            macd_signal=float(last.get("macd_signal")) if pd.notna(last.get("macd_signal")) else None,
            macd_histogram=float(last.get("macd_histogram")) if pd.notna(last.get("macd_histogram")) else None,
            macd_histogram_prev=float(prev.get("macd_histogram")) if pd.notna(prev.get("macd_histogram")) else None,

            ema_9=float(last.get("ema_9")) if pd.notna(last.get("ema_9")) else None,
            ema_21=float(last.get("ema_21")) if pd.notna(last.get("ema_21")) else None,
            ema_50=float(last.get("ema_50")) if pd.notna(last.get("ema_50")) else None,
            ema_200=float(last.get("ema_200")) if pd.notna(last.get("ema_200")) else None,

            bb_upper=float(last.get("bb_upper")) if pd.notna(last.get("bb_upper")) else None,
            bb_middle=float(last.get("bb_middle")) if pd.notna(last.get("bb_middle")) else None,
            bb_lower=float(last.get("bb_lower")) if pd.notna(last.get("bb_lower")) else None,
            bb_width=float(last.get("bb_width")) if pd.notna(last.get("bb_width")) else None,

            atr_14=float(last.get("atr_14")) if pd.notna(last.get("atr_14")) else None,

            volume_sma_20=float(last.get("volume_sma_20")) if pd.notna(last.get("volume_sma_20")) else None,
            volume_ratio=float(last.get("volume_ratio")) if pd.notna(last.get("volume_ratio")) else None,

            funding_rate=funding_rate
        )

    def check_macd_crossover(self, df: pd.DataFrame) -> Optional[str]:
        """
        Sprawdz czy wystapil MACD crossover

        Returns:
            'bullish' - linia MACD przeciela signal od dolu
            'bearish' - linia MACD przeciela signal od gory
            None - brak crossover
        """
        if len(df) < 2:
            return None

        if "macd_histogram" not in df.columns:
            df = self.calculate_all(df)

        curr = df.iloc[-1]["macd_histogram"]
        prev = df.iloc[-2]["macd_histogram"]

        if pd.isna(curr) or pd.isna(prev):
            return None

        if curr > 0 and prev <= 0:
            return "bullish"
        elif curr < 0 and prev >= 0:
            return "bearish"

        return None

    def get_trend_direction(self, df: pd.DataFrame) -> str:
        """
        Okresl kierunek trendu na podstawie EMA

        Returns:
            'strong_up' - cena > EMA9 > EMA21 > EMA50 > EMA200
            'up' - cena > EMA200
            'down' - cena < EMA200
            'strong_down' - cena < EMA9 < EMA21 < EMA50 < EMA200
            'neutral' - brak wyraznego trendu
        """
        if df.empty:
            return "neutral"

        if "ema_200" not in df.columns:
            df = self.calculate_all(df)

        last = df.iloc[-1]
        close = last["close"]
        ema9 = last.get("ema_9")
        ema21 = last.get("ema_21")
        ema50 = last.get("ema_50")
        ema200 = last.get("ema_200")

        if pd.isna(ema200):
            return "neutral"

        # Strong uptrend
        if all(pd.notna([ema9, ema21, ema50, ema200])):
            if close > ema9 > ema21 > ema50 > ema200:
                return "strong_up"
            elif close < ema9 < ema21 < ema50 < ema200:
                return "strong_down"

        # Simple trend
        if close > ema200:
            return "up"
        elif close < ema200:
            return "down"

        return "neutral"
