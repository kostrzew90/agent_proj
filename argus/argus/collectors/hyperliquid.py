import logging
from datetime import datetime, timezone
from sqlalchemy import select
from argus.models import Asset, Claim, ClaimAudit, WalletPosition
from argus.hyperliquid import fetch_positions
from argus.prices import get_spot_price

logger = logging.getLogger(__name__)


def _confidence(position_value: float, equity: float) -> float:
    if equity and equity > 0:
        return round(max(0.5, min(0.9, position_value / equity)), 2)
    return 0.7


def collect_wallet(session, source) -> int:
    data = fetch_positions(source.handle)
    equity = data["equity"]
    scorable = {a.symbol: a for a in session.scalars(select(Asset).where(Asset.scorable == True))}  # noqa: E712
    now = datetime.now(timezone.utc)
    seen = set()
    created = 0
    for pos in data["positions"]:
        coin, side = pos["coin"], pos["side"]
        seen.add(coin)
        wp = session.scalar(select(WalletPosition).where(
            WalletPosition.source_id == source.id, WalletPosition.coin == coin))
        is_new = wp is None or not wp.open
        is_flip = wp is not None and wp.open and wp.side != side
        if (is_new or is_flip) and coin in scorable:
            try:
                spot = get_spot_price(scorable[coin])
            except Exception as e:
                logger.warning("skip wallet claim %s %s: price failed: %s", source.handle, coin, e)
                spot = None
            if spot is not None:
                direction = "bull" if side == "long" else "bear"
                claim = Claim(source_id=source.id, asset=coin, direction=direction,
                              confidence=_confidence(pos["position_value"], equity), method="position",
                              entry_price=spot, entry_ts=now, status="open")
                session.add(claim); session.flush()
                session.add(ClaimAudit(claim_id=claim.id,
                    raw_text=f"{source.display_name} {side} {coin}",
                    parsed_claim={"direction": direction, "coin": coin,
                                  "wallet_entry_px": pos["entry_px"], "detected_px": spot,
                                  "position_value": pos["position_value"], "equity": equity},
                    parser_version="hyperliquid-v1"))
                created += 1
        if wp is None:
            session.add(WalletPosition(source_id=source.id, coin=coin, side=side, szi=pos["szi"],
                                       entry_px=pos["entry_px"], position_value=pos["position_value"],
                                       opened_ts=now, last_seen_ts=now, open=True))
        else:
            if not wp.open or wp.side != side:
                wp.opened_ts = now
            wp.side = side; wp.szi = pos["szi"]; wp.entry_px = pos["entry_px"]
            wp.position_value = pos["position_value"]; wp.last_seen_ts = now; wp.open = True
    for wp in session.scalars(select(WalletPosition).where(
            WalletPosition.source_id == source.id, WalletPosition.open == True)):  # noqa: E712
        if wp.coin not in seen:
            wp.open = False; wp.last_seen_ts = now
    session.commit()
    return created
