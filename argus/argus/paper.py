import os
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select

from argus.models import PaperAccount, PaperTrade

logger = logging.getLogger(__name__)

START_BALANCE = float(os.getenv("ARGUS_PAPER_START", "1000"))
FEE_RATE = 0.0005
REPORT_HOUR = 21  # Europe/Warsaw


def _warsaw(dt: datetime) -> datetime:
    return dt.astimezone(ZoneInfo("Europe/Warsaw"))


def _default_price_fn(session, asset):
    from argus.signals import _last_price
    return _last_price(session, asset)


def get_account(session, now=None) -> PaperAccount:
    acc = session.scalar(select(PaperAccount).order_by(PaperAccount.id))
    if acc is None:
        acc = PaperAccount(
            start_balance=START_BALANCE,
            cash=START_BALANCE,
            started_at=now or datetime.now(timezone.utc),
        )
        session.add(acc)
        session.commit()
    return acc


def _open_trades(session) -> list:
    return list(session.scalars(select(PaperTrade).where(PaperTrade.status == "open")))


def open_trade(session, signal_log, asset_kind, price_fn=None, now=None) -> PaperTrade:
    price_fn = price_fn or _default_price_fn
    now = now or datetime.now(timezone.utc)
    acc = get_account(session, now)
    price = price_fn(session, signal_log.asset)
    if price is None:
        price = signal_log.entry_price
    horizon = 168 if (signal_log.tier == "confluence" and asset_kind == "stock") else 24
    equity = acc.cash + sum(t.notional for t in _open_trades(session))
    notional = equity * signal_log.position_pct
    entry_fee = notional * FEE_RATE
    trade = PaperTrade(
        signal_id=signal_log.id,
        asset=signal_log.asset,
        direction=signal_log.direction,
        horizon_hours=horizon,
        opened_at=now,
        fees=0.0,
    )
    if notional + entry_fee > acc.cash:
        trade.status = "skipped"
    else:
        acc.cash -= notional + entry_fee
        trade.status = "open"
        trade.entry_price = price
        trade.qty = notional / price
        trade.notional = notional
        trade.stop_price = signal_log.stop_price
        trade.fees = entry_fee
        trade.last_price = price
        trade.last_price_at = now
    session.add(trade)
    session.commit()
    return trade


def _gross(t: PaperTrade, price: float) -> float:
    if t.direction == "bull":
        return t.qty * (price - t.entry_price)
    return t.qty * (t.entry_price - price)


def _close(acc, t: PaperTrade, price: float, reason: str, now) -> None:
    gross = _gross(t, price)
    exit_fee = t.qty * price * FEE_RATE
    acc.cash += t.notional + gross - exit_fee
    t.fees += exit_fee
    t.pnl = gross - t.fees
    t.exit_price = price
    t.exit_reason = reason
    t.closed_at = now
    t.status = "closed"


def tick(session, price_fn=None, now=None) -> None:
    price_fn = price_fn or _default_price_fn
    now = now or datetime.now(timezone.utc)
    trades = _open_trades(session)
    if not trades:
        return
    acc = get_account(session, now)
    for t in trades:
        price = price_fn(session, t.asset)
        if price is not None:
            t.last_price = price
            t.last_price_at = now
        age = now - t.opened_at
        stop_hit = price is not None and (
            price <= t.stop_price if t.direction == "bull" else price >= t.stop_price
        )
        if stop_hit:
            _close(acc, t, price, "stop", now)
        elif price is not None and age >= timedelta(hours=t.horizon_hours):
            _close(acc, t, price, "horizon", now)
        elif age >= timedelta(hours=t.horizon_hours + 24):
            _close(acc, t, t.last_price, "stale", now)
    session.commit()


def build_report(session, now) -> str:
    acc = get_account(session, now)
    today = _warsaw(now).date()
    open_trades = _open_trades(session)
    unreal = {t.id: _gross(t, t.last_price) for t in open_trades}
    balance = acc.cash + sum(t.notional + unreal[t.id] for t in open_trades)
    change = balance - acc.start_balance
    pct = change / acc.start_balance * 100 if acc.start_balance else 0.0

    closed_today = [
        t for t in session.scalars(select(PaperTrade).where(PaperTrade.status == "closed"))
        if t.closed_at is not None and _warsaw(t.closed_at).date() == today
    ]
    skipped = list(session.scalars(select(PaperTrade).where(PaperTrade.status == "skipped")))
    skipped_today = sum(1 for t in skipped if _warsaw(t.opened_at).date() == today)
    days = (today - _warsaw(acc.started_at).date()).days

    reasons = {"stop": "stop", "horizon": "koniec horyzontu", "stale": "brak ceny"}
    directions = {"bull": "long", "bear": "short"}
    lines = [
        f"💰 Wirtualne konto — {today.isoformat()}",
        f"Saldo: ${balance:,.2f} (start ${acc.start_balance:,.2f}), zmiana {change:+,.2f}$ ({pct:+.2f}%)",
        f"Gotówka: ${acc.cash:,.2f}, dzień konta: {days}",
        "",
        f"Zamknięte dziś: {len(closed_today)}, P&L ${sum(t.pnl for t in closed_today):+,.2f}",
    ]
    for t in closed_today:
        lines.append(
            f"- {t.asset} {directions.get(t.direction, t.direction)} "
            f"({reasons.get(t.exit_reason, t.exit_reason)}): ${t.pnl:+,.2f}"
        )
    lines.append("")
    lines.append(f"Otwarte pozycje: {len(open_trades)}")
    for t in open_trades:
        lines.append(
            f"- {t.asset} {directions.get(t.direction, t.direction)}: "
            f"${unreal[t.id]:+,.2f} (niezrealizowane)"
        )
    lines.append("")
    lines.append(f"Pominięte sygnały (brak gotówki): dziś {skipped_today}, łącznie {len(skipped)}")
    return "\n".join(lines)
