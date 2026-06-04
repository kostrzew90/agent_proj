from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from argus.db import Base
import argus.models  # noqa
from argus.models import Asset, Source, SourceScore
from argus.api import app, get_session

def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    def override():
        s = Sess()
        try: yield s
        finally: s.close()
    app.dependency_overrides[get_session] = override
    return TestClient(app), Sess

def test_health():
    client, _ = _client()
    assert client.get("/health").json() == {"status": "ok"}

def test_assets_and_sources_endpoints():
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    src = Source(kind="rss", handle="h", display_name="CoinDesk"); s.add(src); s.flush()
    s.add(SourceScore(source_id=src.id, horizon="24h", n_claims=5, hit_rate=0.6,
                      avg_return=0.02, decayed_score=0.58,
                      updated_at=datetime.now(timezone.utc)))
    s.commit()
    assert client.get("/api/assets?horizon=24h").status_code == 200
    leaders = client.get("/api/sources?horizon=24h").json()
    assert leaders[0]["display_name"] == "CoinDesk"
    assert leaders[0]["decayed_score"] == 0.58

def test_candles_ok():
    from unittest.mock import patch
    from argus.models import Asset
    client, Sess = _client()
    s = Sess(); s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)); s.commit()
    fake = [{"time": 1717200000, "open": 67000.0, "high": 67500.0, "low": 66800.0, "close": 67200.0}]
    with patch("argus.api.get_candles", return_value=fake):
        r = client.get("/api/candles?asset=BTC")
    assert r.status_code == 200
    assert r.json() == fake

def test_candles_unknown_asset_404():
    client, _ = _client()
    assert client.get("/api/candles?asset=NOPE").status_code == 404

def test_candles_provider_failure_502():
    from unittest.mock import patch
    from argus.models import Asset
    client, Sess = _client()
    s = Sess(); s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)); s.commit()
    with patch("argus.api.get_candles", side_effect=RuntimeError("binance down")):
        r = client.get("/api/candles?asset=BTC")
    assert r.status_code == 502

def test_assets_includes_scorable_without_claims():
    from argus.models import Asset
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="LCID", kind="stock", yf_symbol="LCID", scorable=True))   # no claims
    s.add(Asset(symbol="TOTAL", kind="index", scorable=False))                   # excluded
    s.commit()
    rows = client.get("/api/assets?horizon=1h").json()
    symbols = {r["asset"] for r in rows}
    assert "LCID" in symbols
    assert "TOTAL" not in symbols
    lcid = next(r for r in rows if r["asset"] == "LCID")
    assert lcid["lean"] == 0.0
    assert lcid["kind"] == "stock"

def test_asset_detail_claims_and_sources():
    from datetime import datetime, timezone
    from argus.models import Asset, Source, Claim, Outcome, SourceAssetScore
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="h", display_name="CoinDesk"); s.add(src); s.flush()
    now = datetime.now(timezone.utc)
    c = Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.8, method="rule",
              entry_price=100.0, entry_ts=now, status="open"); s.add(c); s.flush()
    s.add(Outcome(claim_id=c.id, horizon="1h", eval_ts=now, price_at_horizon=102.0,
                  return_pct=0.02, hit=True))
    s.add(SourceAssetScore(source_id=src.id, asset="BTC", horizon="1h", n_claims=1, n_hits=1,
                           hit_rate=1.0, avg_return=0.02, decayed_score=0.7, updated_at=now))
    s.commit()
    d = client.get("/api/asset/BTC?horizon=1h").json()
    assert d["claims"][0]["source"] == "CoinDesk"
    assert d["claims"][0]["direction"] == "bull"
    assert d["claims"][0]["hit"] is True
    assert d["sources"][0]["display_name"] == "CoinDesk"
    assert d["sources"][0]["decayed_score"] == 0.7

def test_wallet_preview_validates_and_lists():
    from unittest.mock import patch
    client, _ = _client()
    assert client.get("/api/wallets/preview?address=bad").status_code == 422
    fake = {"equity": 10000.0, "positions": [{"coin": "BTC", "side": "long", "position_value": 8000.0}]}
    with patch("argus.api.fetch_positions", return_value=fake):
        r = client.get("/api/wallets/preview?address=0x" + "a"*40)
    assert r.status_code == 200
    assert r.json()["positions"][0]["coin"] == "BTC"

def test_wallet_add_and_list_and_deactivate():
    from datetime import datetime, timezone
    from argus.models import Source, SourceScore
    client, Sess = _client()
    addr = "0x" + "b"*40
    assert client.post("/api/wallets", json={"address": "nope"}).status_code == 422
    r = client.post("/api/wallets", json={"address": addr, "label": "whale-x"})
    assert r.status_code == 200
    client.post("/api/wallets", json={"address": addr, "label": "whale-x"})  # idempotent
    s = Sess()
    src = s.query(Source).filter_by(handle=addr).one()
    s.add(SourceScore(source_id=src.id, horizon="24h", n_claims=3, hit_rate=0.66,
                      avg_return=0.01, decayed_score=0.6, updated_at=datetime.now(timezone.utc)))
    s.commit()
    rows = client.get("/api/wallets").json()
    row = next(r for r in rows if r["handle"] == addr)
    assert row["acc_24h"] == 0.66 and row["display_name"] == "whale-x"
    assert client.post(f"/api/wallets/{src.id}/deactivate").status_code == 200
    s.expire_all()
    assert s.get(Source, src.id).active is False
