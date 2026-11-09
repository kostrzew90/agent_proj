from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from argus import paper
from argus.db import Base
from argus.models import SignalLog, PaperTrade, PaperAccount, Asset, Source, WalletPosition
from argus.paper import FEE_RATE

T0 = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


def _sig(session, asset="BTC", direction="bull", tier="whale", entry=100.0,
         stop=95.0, pct=0.10):
    log = SignalLog(tier=tier, asset=asset, direction=direction, source_ids="[1]",
                    signal_strength=0.5, entry_price=entry, stop_price=stop,
                    position_pct=pct, sent_at=T0)
    session.add(log)
    session.commit()
    return log


def _px(value):
    return lambda session, asset: value


def test_ac1_open_trade(session):
    log = _sig(session)
    t = paper.open_trade(session, log, "crypto", price_fn=_px(100.0), now=T0)
    acc = paper.get_account(session)
    fee = 100.0 * FEE_RATE
    assert t.status == "open"
    assert t.entry_price == 100.0
    assert t.notional == pytest.approx(100.0)  # 1000 * 0.10
    assert t.qty == pytest.approx(1.0)
    assert t.stop_price == 95.0
    assert t.horizon_hours == 24
    assert acc.cash == pytest.approx(1000.0 - 100.0 - fee)


def test_ac1_fallback_to_signal_price_and_stock_confluence_horizon(session):
    log = _sig(session, tier="confluence", entry=50.0, stop=48.0)
    t = paper.open_trade(session, log, "stock", price_fn=_px(None), now=T0)
    assert t.entry_price == 50.0
    assert t.horizon_hours == 168


def test_ac2_stop_bull(session):
    log = _sig(session)
    paper.open_trade(session, log, "crypto", price_fn=_px(100.0), now=T0)
    paper.tick(session, price_fn=_px(94.0), now=T0 + timedelta(hours=1))
    t = session.scalar(select(PaperTrade))
    assert t.status == "closed" and t.exit_reason == "stop"
    fees = 100.0 * FEE_RATE + 94.0 * FEE_RATE
    assert t.pnl == pytest.approx(-6.0 - fees)
    acc = paper.get_account(session)
    assert acc.cash == pytest.approx(1000.0 + t.pnl)


def test_ac2_stop_bear(session):
    log = _sig(session, direction="bear", stop=105.0)
    paper.open_trade(session, log, "crypto", price_fn=_px(100.0), now=T0)
    paper.tick(session, price_fn=_px(106.0), now=T0 + timedelta(hours=1))
    t = session.scalar(select(PaperTrade))
    assert t.exit_reason == "stop"
    fees = 100.0 * FEE_RATE + 106.0 * FEE_RATE
    assert t.pnl == pytest.approx(-6.0 - fees)


def test_ac2_horizon(session):
    log = _sig(session)
    paper.open_trade(session, log, "crypto", price_fn=_px(100.0), now=T0)
    paper.tick(session, price_fn=_px(102.0), now=T0 + timedelta(hours=10))
    assert session.scalar(select(PaperTrade)).status == "open"
    paper.tick(session, price_fn=_px(110.0), now=T0 + timedelta(hours=24))
    t = session.scalar(select(PaperTrade))
    assert t.status == "closed" and t.exit_reason == "horizon"
    fees = 100.0 * FEE_RATE + 110.0 * FEE_RATE
    assert t.pnl == pytest.approx(10.0 - fees)
    assert paper.get_account(session).cash == pytest.approx(1000.0 + 10.0 - fees)


def test_ac3_skipped_when_no_cash(session):
    acc = paper.get_account(session, T0)
    acc.cash = 50.0
    session.commit()
    # equity 50, notional 100% -> notional+fee > cash
    log = _sig(session, pct=1.0)
    t = paper.open_trade(session, log, "crypto", price_fn=_px(100.0), now=T0)
    assert t.status == "skipped"
    assert paper.get_account(session).cash == 50.0
    report = paper.build_report(session, T0)
    assert "dziś 1, łącznie 1" in report


def test_ac4_stale_closes_at_last_known_price(session):
    log = _sig(session)
    paper.open_trade(session, log, "crypto", price_fn=_px(100.0), now=T0)
    paper.tick(session, price_fn=_px(103.0), now=T0 + timedelta(hours=5))
    paper.tick(session, price_fn=_px(None), now=T0 + timedelta(hours=30))
    assert session.scalar(select(PaperTrade)).status == "open"
    paper.tick(session, price_fn=_px(None), now=T0 + timedelta(hours=48))
    t = session.scalar(select(PaperTrade))
    assert t.status == "closed" and t.exit_reason == "stale"
    assert t.exit_price == 103.0


def test_ac6_state_persists(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}", future=True)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s1 = Sess()
    log = _sig(s1)
    paper.open_trade(s1, log, "crypto", price_fn=_px(100.0), now=T0)
    cash = paper.get_account(s1).cash
    s1.close()
    s2 = Sess()
    assert paper.get_account(s2).cash == pytest.approx(cash)
    trades = list(s2.scalars(select(PaperTrade)))
    assert len(trades) == 1 and trades[0].status == "open"
    assert s2.scalar(select(PaperAccount).limit(1)) is not None
    s2.close()
    engine.dispose()


def test_send_signals_survives_paper_failure(session):
    from argus.signals import send_signals, SignalResult
    result = SignalResult(
        tier="whale", asset="BTC", asset_kind="crypto", direction="bull",
        source_ids=[1], source_labels=["x"], signal_strength=0.5,
        entry_price=100.0, stop_price=95.0, position_pct=0.1, risk_pct=0.005,
        stop_pct=0.05, vol_tier="large", horizon="24h", window_str=None,
        whale_notional=None)
    with patch("argus.signals.send_message") as send,             patch("argus.signals.check_whale_signals", return_value=[result]),             patch("argus.signals.check_confluence_signals", return_value=[]),             patch("argus.signals.check_liquidation_signals", return_value=[]),             patch("argus.paper.open_trade", side_effect=RuntimeError("boom")):
        send_signals(session)
    send.assert_called_once()
    assert session.scalar(select(SignalLog)) is not None
