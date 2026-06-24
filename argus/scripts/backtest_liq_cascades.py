"""
One-off backtest: decide the liquidation-cascade direction_rule (contrarian vs
continuation) per asset, using real historical `liquidations` + price data.
Not part of the live app — run manually, read the report, edit
config/liq_cascade_rules.yaml by hand based on the result.

Usage (inside the Argus container, where DATABASE_URL is already configured):
    python -m scripts.backtest_liq_cascades
"""
import statistics
from datetime import timedelta, timezone
from sqlalchemy import select

from argus.db import SessionLocal
from argus.models import Asset, Liquidation
from argus.liquidations.cascade import detect_cascades, annotate_price_context
from argus.prices import get_historical_price

WINDOW_CANDIDATES = [15, 30, 60]
NOTIONAL_CANDIDATES = [10_000, 25_000, 50_000, 100_000]
HORIZONS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
MIN_EVENTS_REQUIRED = 25

# review pkt 4: does requiring momentum INTO the liquidation (price already moving
# the way that would cause this side to get liquidated) change the hit rate vs no filter?
MOMENTUM_THRESHOLD = 0.01  # 1% move in the 15min before the cascade counts as "momentum present"


def _has_momentum(cascade) -> bool:
    if cascade.price_change_window is None:
        return False
    # long_liq cascades happen because price fell; short_liq because price rose
    if cascade.side == "long_liq":
        return cascade.price_change_window <= -MOMENTUM_THRESHOLD
    return cascade.price_change_window >= MOMENTUM_THRESHOLD


def _evaluate_cascade(asset_row, cascade, horizon_delta):
    entry = get_historical_price(asset_row, cascade.window_end)
    later = get_historical_price(asset_row, cascade.window_end + horizon_delta)
    ret = (later - entry) / entry
    # contrarian hypothesis: long_liq -> expect price UP (ret > 0); short_liq -> expect DOWN
    contrarian_hit = ret > 0 if cascade.side == "long_liq" else ret < 0
    continuation_hit = not contrarian_hit
    return ret, contrarian_hit, continuation_hit


def _report_row(label, asset_symbol, window_minutes, min_notional, horizon_name,
                 asset_row, cascades, horizon_delta):
    if len(cascades) < MIN_EVENTS_REQUIRED:
        print(f"{label:<10} {asset_symbol:<6} {window_minutes:>7} {min_notional:>13.0f} "
              f"{horizon_name:>8} {len(cascades):>5}  insufficient_data (need >= {MIN_EVENTS_REQUIRED})")
        return
    returns, contrarian_hits, continuation_hits = [], [], []
    for c in cascades:
        try:
            ret, c_hit, k_hit = _evaluate_cascade(asset_row, c, horizon_delta)
        except Exception as e:
            print(f"  skip {asset_symbol} {c.window_end}: {e}")
            continue
        returns.append(ret)
        contrarian_hits.append(c_hit)
        continuation_hits.append(k_hit)
    if not returns:
        return
    buy_hold = statistics.mean(returns)
    contrarian_rate = sum(contrarian_hits) / len(contrarian_hits)
    continuation_rate = sum(continuation_hits) / len(continuation_hits)
    print(f"{label:<10} {asset_symbol:<6} {window_minutes:>7} {min_notional:>13.0f} "
          f"{horizon_name:>8} {len(returns):>5} {0.50:>8.0%} {buy_hold:>10.2%} "
          f"{contrarian_rate:>11.0%} {continuation_rate:>13.0%}")


def run_backtest():
    with SessionLocal() as s:
        all_liqs = list(s.scalars(select(Liquidation).order_by(Liquidation.ts)))
        assets = {a.symbol: a for a in s.scalars(select(Asset))}

        print(f"Total liquidation rows: {len(all_liqs)}")
        print(f"{'variant':<10} {'asset':<6} {'window':>7} {'min_notional':>13} {'horizon':>8} "
              f"{'n':>5} {'random':>8} {'buy&hold':>10} {'contrarian':>11} {'continuation':>13}")

        for window_minutes in WINDOW_CANDIDATES:
            for min_notional in NOTIONAL_CANDIDATES:
                cascades = detect_cascades(all_liqs, window_minutes, min_notional)
                annotate_price_context(s, cascades)
                by_asset: dict[str, list] = {}
                for c in cascades:
                    by_asset.setdefault(c.asset, []).append(c)

                for asset_symbol, asset_cascades in by_asset.items():
                    asset_row = assets.get(asset_symbol)
                    if asset_row is None:
                        continue

                    # review pkt 5: cascade_intensity as an alternative threshold —
                    # keep only the top half by intensity within this bucket, see if
                    # that subset is more predictive than the raw notional threshold alone.
                    intensities = sorted(c.cascade_intensity for c in asset_cascades)
                    intensity_median = intensities[len(intensities) // 2]
                    high_intensity = [c for c in asset_cascades if c.cascade_intensity >= intensity_median]

                    # review pkt 4: momentum filter — only cascades where price was
                    # already moving the way that caused this side to get liquidated.
                    with_momentum = [c for c in asset_cascades if _has_momentum(c)]

                    for horizon_name, horizon_delta in HORIZONS.items():
                        _report_row("all", asset_symbol, window_minutes, min_notional,
                                    horizon_name, asset_row, asset_cascades, horizon_delta)
                        _report_row("intensity", asset_symbol, window_minutes, min_notional,
                                    horizon_name, asset_row, high_intensity, horizon_delta)
                        _report_row("momentum", asset_symbol, window_minutes, min_notional,
                                    horizon_name, asset_row, with_momentum, horizon_delta)


if __name__ == "__main__":
    run_backtest()
