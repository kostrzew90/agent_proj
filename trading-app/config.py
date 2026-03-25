"""
Trading Agent Configuration
"""
import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DatabaseConfig:
    host: str = os.getenv("DB_HOST", "postgres")
    port: int = int(os.getenv("DB_PORT", "5432"))
    user: str = os.getenv("DB_USER", "n8n")
    password: str = os.getenv("DB_PASSWORD", "n8npass")
    database: str = os.getenv("DB_NAME", "n8n")

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class GateIOConfig:
    api_key: str = os.getenv("GATE_API_KEY", "")
    api_secret: str = os.getenv("GATE_API_SECRET", "")
    use_testnet: bool = os.getenv("GATE_USE_TESTNET", "true").lower() == "true"

    @property
    def base_url(self) -> str:
        if self.use_testnet:
            return "https://fx-api-testnet.gateio.ws/api/v4"
        return "https://api.gateio.ws/api/v4"


@dataclass
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    model_chat: str = os.getenv("OLLAMA_MODEL_CHAT", "qwen3:4b")
    model_embedding: str = os.getenv("OLLAMA_MODEL_EMBEDDING", "qwen3-embedding:0.6b")
    timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "30"))


@dataclass
class ClaudeConfig:
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
    enabled: bool = os.getenv("CLAUDE_BACKUP_ENABLED", "true").lower() == "true"


@dataclass
class RSIConfig:
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    extreme_oversold: float = 20.0
    extreme_overbought: float = 80.0


@dataclass
class MACDConfig:
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9


@dataclass
class EMAConfig:
    short: int = 9
    medium: int = 21
    long: int = 50
    trend: int = 200


@dataclass
class BollingerConfig:
    period: int = 20
    std_dev: float = 2.0


@dataclass
class ATRConfig:
    period: int = 14
    sl_multiplier: float = 1.5
    tp_multiplier: float = 3.0


@dataclass
class IndicatorsConfig:
    rsi: RSIConfig = field(default_factory=RSIConfig)
    macd: MACDConfig = field(default_factory=MACDConfig)
    ema: EMAConfig = field(default_factory=EMAConfig)
    bollinger: BollingerConfig = field(default_factory=BollingerConfig)
    atr: ATRConfig = field(default_factory=ATRConfig)


@dataclass
class SignalConfig:
    min_score: int = 5
    min_confidence: float = 0.5
    timeframes: List[str] = field(default_factory=lambda: ["5m", "15m", "1h"])


@dataclass
class RiskConfig:
    paper_trading: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"
    trading_enabled: bool = os.getenv("TRADING_ENABLED", "false").lower() == "true"
    daily_loss_limit_percent: float = float(os.getenv("DAILY_LOSS_LIMIT", "2.0"))
    max_position_size_percent: float = float(os.getenv("MAX_POSITION_SIZE", "10.0"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
    default_leverage: int = int(os.getenv("DEFAULT_LEVERAGE", "5"))
    max_leverage: int = int(os.getenv("MAX_LEVERAGE", "10"))


@dataclass
class SchedulerConfig:
    market_data_interval: int = 60  # seconds
    signals_interval: int = 300  # 5 minutes
    monitor_interval: int = 30  # seconds
    risk_check_interval: int = 60  # seconds
    liquidity_scan_interval: int = 900  # 15 minutes


@dataclass
class Config:
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    gate: GateIOConfig = field(default_factory=GateIOConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    indicators: IndicatorsConfig = field(default_factory=IndicatorsConfig)
    signals: SignalConfig = field(default_factory=SignalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)

    # Trading symbols
    symbols: List[str] = field(default_factory=lambda: ["BTC_USDT", "ETH_USDT"])


# Global config instance
config = Config()
