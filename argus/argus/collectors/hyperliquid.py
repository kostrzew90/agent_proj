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


def compute_consensus(session, min_wallets: int = 4, ratio: float = 0.66) -> int:
    from argus.models import Source
    cons = session.scalar(select(Source).where(Source.kind == "derived",
                                               Source.handle == "whale-consensus"))
    if cons is None:
        return 0
    scorable = {a.symbol: a for a in session.scalars(select(Asset).where(Asset.scorable == True))}  # noqa: E712
    hl_ids = [s.id for s in session.scalars(select(Source).where(
        Source.kind == "hyperliquid", Source.active == True))]  # noqa: E712
    now = datetime.now(timezone.utc)
    tally = {}  # coin -> [longs, shorts]
    for wp in session.scalars(select(WalletPosition).where(
            WalletPosition.open == True, WalletPosition.source_id.in_(hl_ids or [-1]))):  # noqa: E712
        if wp.coin not in scorable:
            continue
        t = tally.setdefault(wp.coin, [0, 0])
        t[0 if wp.side == "long" else 1] += 1
    created = 0
    for coin, (longs, shorts) in tally.items():
        total = longs + shorts
        if total < min_wallets:
            continue
        if longs / total >= ratio:
            side = "long"
        elif shorts / total >= ratio:
            side = "short"
        else:
            continue
        state = session.scalar(select(WalletPosition).where(
            WalletPosition.source_id == cons.id, WalletPosition.coin == coin))
        if state is not None and state.open and state.side == side:
            continue  # unchanged consensus
        try:
            spot = get_spot_price(scorable[coin])
        except Exception as e:
            logger.warning("consensus skip %s: price failed: %s", coin, e)
            continue
        direction = "bull" if side == "long" else "bear"
        claim = Claim(source_id=cons.id, asset=coin, direction=direction,
                      confidence=round(max(longs, shorts) / total, 2), method="position",
                      entry_price=spot, entry_ts=now, status="open")
        session.add(claim); session.flush()
        session.add(ClaimAudit(claim_id=claim.id, raw_text=f"consensus {side} {coin} {longs}L/{shorts}S",
                    parsed_claim={"direction": direction, "coin": coin, "longs": longs, "shorts": shorts},
                    parser_version="consensus-v1"))
        if state is None:
            session.add(WalletPosition(source_id=cons.id, coin=coin, side=side, szi=0.0, entry_px=spot,
                                       position_value=0.0, opened_ts=now, last_seen_ts=now, open=True))
        else:
            state.side = side; state.open = True; state.last_seen_ts = now; state.opened_ts = now
        created += 1
    session.commit()
    return created
