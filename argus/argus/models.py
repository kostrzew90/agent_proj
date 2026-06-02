from datetime import datetime
from sqlalchemy import (String, Float, Boolean, Integer, DateTime, ForeignKey, JSON, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column
from argus.db import Base

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
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Float)

class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("claim_id", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    horizon: Mapped[str] = mapped_column(String)              # 1h|24h|7d
    eval_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price_at_horizon: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)
    hit: Mapped[bool] = mapped_column(Boolean)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class SourceAssetScore(Base):
    __tablename__ = "source_asset_scores"
    __table_args__ = (UniqueConstraint("source_id", "asset", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    asset: Mapped[str] = mapped_column(String)
    horizon: Mapped[str] = mapped_column(String)
    n_claims: Mapped[int] = mapped_column(Integer)
    n_hits: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float] = mapped_column(Float)
    avg_return: Mapped[float] = mapped_column(Float)
    decayed_score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class SourceScore(Base):
    __tablename__ = "source_scores"
    __table_args__ = (UniqueConstraint("source_id", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    horizon: Mapped[str] = mapped_column(String)
    n_claims: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float] = mapped_column(Float)
    avg_return: Mapped[float] = mapped_column(Float)
    decayed_score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
