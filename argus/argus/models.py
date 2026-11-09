from datetime import datetime, date as date_type
from sqlalchemy import (String, Float, Boolean, Integer, Date, DateTime, ForeignKey, JSON, UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column
from argus.db import Base, TZDateTime

class Asset(Base):
    __tablename__ = "assets"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)                 # crypto|stock|index|macro
    coingecko_id: Mapped[str | None] = mapped_column(String, nullable=True)
    binance_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    yf_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    scorable: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)                 # rss|hyperdash|reddit|onchain
    handle: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    direction: Mapped[str] = mapped_column(String)            # bull|bear|neutral
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String)               # position|rule|llm
    entry_price: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[datetime] = mapped_column(TZDateTime())
    status: Mapped[str] = mapped_column(String, default="open")

class ClaimAudit(Base):
    __tablename__ = "claim_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    raw_text: Mapped[str] = mapped_column(String)
    parsed_claim: Mapped[dict] = mapped_column(JSON)
    parser_version: Mapped[str] = mapped_column(String)

class Price(Base):
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    ts: Mapped[datetime] = mapped_column(TZDateTime())
    price: Mapped[float] = mapped_column(Float)

class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("claim_id", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    horizon: Mapped[str] = mapped_column(String)              # 1h|24h|7d
    eval_ts: Mapped[datetime] = mapped_column(TZDateTime())
    price_at_horizon: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)
    hit: Mapped[bool] = mapped_column(Boolean)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

class SourceAssetScore(Base):
    __tablename__ = "source_asset_scores"
    __table_args__ = (UniqueConstraint("source_id", "asset", "horizon", "direction"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    asset: Mapped[str] = mapped_column(String)
    horizon: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String, default="all")  # bull|bear|all
    n_claims: Mapped[int] = mapped_column(Integer)
    n_hits: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float] = mapped_column(Float)
    avg_return: Mapped[float] = mapped_column(Float)
    decayed_score: Mapped[float] = mapped_column(Float)
    cohort_rate: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime())

class SourceScore(Base):
    __tablename__ = "source_scores"
    __table_args__ = (UniqueConstraint("source_id", "horizon", "direction"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    horizon: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String, default="all")  # bull|bear|all
    n_claims: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float] = mapped_column(Float)
    avg_return: Mapped[float] = mapped_column(Float)
    decayed_score: Mapped[float] = mapped_column(Float)
    cohort_rate: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime())

class WalletPosition(Base):
    __tablename__ = "wallet_positions"
    __table_args__ = (UniqueConstraint("source_id", "coin"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    coin: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)              # long|short
    szi: Mapped[float] = mapped_column(Float)
    entry_px: Mapped[float] = mapped_column(Float)
    position_value: Mapped[float] = mapped_column(Float)
    opened_ts: Mapped[datetime] = mapped_column(TZDateTime())
    last_seen_ts: Mapped[datetime] = mapped_column(TZDateTime())
    open: Mapped[bool] = mapped_column(Boolean)

class Liquidation(Base):
    __tablename__ = "liquidations"
    __table_args__ = (
        Index("idx_liquidations_asset_ts", "asset", "ts"),
        Index("idx_liquidations_ts", "ts"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    exchange: Mapped[str] = mapped_column(String, default="binance")
    side: Mapped[str] = mapped_column(String)              # long_liq|short_liq
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[float] = mapped_column(Float)
    notional_usd: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(TZDateTime())
    raw_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime())

class MacroData(Base):
    __tablename__ = "macro_data"
    __table_args__ = (UniqueConstraint("series_id", "obs_date"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[str] = mapped_column(String)             # FRED series id
    obs_date: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    value: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime())

class LlmCache(Base):
    __tablename__ = "llm_cache"
    text_hash: Mapped[str] = mapped_column(String, primary_key=True)
    result_json: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZDateTime())

class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZDateTime())
    provider: Mapped[str] = mapped_column(String)            # gemini|openrouter
    model: Mapped[str] = mapped_column(String)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

class LlmQueue(Base):
    __tablename__ = "llm_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), unique=True)
    text_hash: Mapped[str] = mapped_column(String)
    source_kind: Mapped[str] = mapped_column(String)        # reddit|news
    status: Mapped[str] = mapped_column(String)             # pending|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    enqueued_at: Mapped[datetime] = mapped_column(TZDateTime())
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

class SignalLog(Base):
    __tablename__ = "signal_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier: Mapped[str] = mapped_column(String)           # "whale" | "confluence"
    asset: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)      # "bull" | "bear"
    source_ids: Mapped[str] = mapped_column(String)     # JSON list of ints
    signal_strength: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    position_pct: Mapped[float] = mapped_column(Float)
    sent_at: Mapped[datetime] = mapped_column(TZDateTime())
    fng_value: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FearGreed(Base):
    __tablename__ = "fear_greed"
    date: Mapped[date_type] = mapped_column(Date, primary_key=True)
    value: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signal_log.id"))
    asset: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    price_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_stop: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)  # open|win|loss|stopped
    evaluated_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class PaperAccount(Base):
    __tablename__ = "paper_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_balance: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_report_date: Mapped[str | None] = mapped_column(String, nullable=True)  # ISO date (Warsaw)


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signal_log.id"), unique=True)
    asset: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)      # "bull" | "bear"
    status: Mapped[str] = mapped_column(String)         # open|closed|skipped
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizon_hours: Mapped[int] = mapped_column(Integer)
    opened_at: Mapped[datetime] = mapped_column(TZDateTime())
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String, nullable=True)  # stop|horizon|stale
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)  # net, after both fees
