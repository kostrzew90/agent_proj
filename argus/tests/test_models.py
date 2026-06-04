from datetime import datetime, timezone
from argus.models import (Asset, Source, Item, Claim, ClaimAudit,
                          Price, Outcome, SourceAssetScore, SourceScore)

def test_full_chain_roundtrip(session):
    a = Asset(symbol="BTC", kind="crypto", coingecko_id="bitcoin",
              binance_symbol="BTCUSDT", scorable=True)
    s = Source(kind="rss", handle="http://x", display_name="X")
    session.add_all([a, s]); session.flush()
    it = Item(source_id=s.id, external_id="e1", title="t", text="long btc",
              url="u", published_at=datetime.now(timezone.utc))
    session.add(it); session.flush()
    c = Claim(source_id=s.id, item_id=it.id, asset="BTC", direction="bull",
              confidence=0.8, method="rule", entry_price=100.0,
              entry_ts=datetime.now(timezone.utc), status="open")
    session.add(c); session.flush()
    session.add(ClaimAudit(claim_id=c.id, raw_text="long btc",
                           parsed_claim={"direction": "bull"}, parser_version="rule-v1"))
    session.add(Outcome(claim_id=c.id, horizon="24h",
                        eval_ts=datetime.now(timezone.utc), price_at_horizon=102.0,
                        return_pct=0.02, hit=True))
    session.commit()
    assert session.query(Claim).one().direction == "bull"
    assert session.query(Outcome).one().hit is True

def test_wallet_position_roundtrip(session):
    from datetime import datetime, timezone
    from argus.models import Source, WalletPosition
    s = Source(kind="hyperliquid", handle="0xabc", display_name="w1"); session.add(s); session.flush()
    now = datetime.now(timezone.utc)
    session.add(WalletPosition(source_id=s.id, coin="BTC", side="long", szi=0.5,
                               entry_px=67000.0, position_value=33500.0,
                               opened_ts=now, last_seen_ts=now, open=True))
    session.commit()
    wp = session.query(WalletPosition).one()
    assert wp.coin == "BTC" and wp.side == "long" and wp.open is True
