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
