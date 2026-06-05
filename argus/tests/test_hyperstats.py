from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from sqlalchemy import select
from argus.models import Source
from argus.collectors.hyperstats import fetch_leaderboard, _passes_filter, sync_top_traders

NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)

def _t(**kw):
    base = {"address": "0x" + "a"*40, "winRate": 0.7, "totalTrades": 100,
            "lastActivityAt": "2026-06-04T00:00:00Z", "totalPnl": 1000.0, "grade": "A"}
    base.update(kw)
    return base

def test_fetch_leaderboard_parses_and_limits():
    resp = MagicMock(); resp.raise_for_status.return_value = None
    resp.json.return_value = {"traders": [{"address": "0x1"}, {"address": "0x2"}]}
    with patch("argus.collectors.hyperstats.httpx.get", return_value=resp) as g:
        out = fetch_leaderboard(limit=50)
    assert len(out) == 2 and out[0]["address"] == "0x1"
    assert g.call_args.kwargs["params"]["limit"] == 50

def test_filter_accepts_good():
    assert _passes_filter(_t(), 0.5, 50, 14, NOW) is True

def test_filter_rejects_low_winrate():
    assert _passes_filter(_t(winRate=0.3), 0.5, 50, 14, NOW) is False

def test_filter_rejects_few_trades():
    assert _passes_filter(_t(totalTrades=10), 0.5, 50, 14, NOW) is False

def test_filter_rejects_stale():
    assert _passes_filter(_t(lastActivityAt="2026-05-01T00:00:00Z"), 0.5, 50, 14, NOW) is False

def test_filter_negative_pnl_low_grade_rejected():
    assert _passes_filter(_t(totalPnl=-5.0, grade="C"), 0.5, 50, 14, NOW) is False

def test_filter_negative_pnl_high_grade_ok():
    assert _passes_filter(_t(totalPnl=-5.0, grade="S+"), 0.5, 50, 14, NOW) is True

def test_sync_inserts_new_skips_existing_and_inactive(session):
    session.add(Source(kind="hyperliquid", handle="0x" + "b"*40, display_name="mine", active=True))
    session.add(Source(kind="hyperliquid", handle="0x" + "c"*40, display_name="off", active=False))
    session.commit()
    recent = datetime.now(timezone.utc).isoformat()
    def mk(addr, **kw):
        d = {"address": addr, "winRate": 0.7, "totalTrades": 100, "lastActivityAt": recent,
             "totalPnl": 1.0, "grade": "A"}
        d.update(kw); return d
    traders = [mk("0x" + "a"*40), mk("0x" + "b"*40), mk("0x" + "c"*40), mk("0x" + "d"*40, winRate=0.1)]
    with patch("argus.collectors.hyperstats.fetch_leaderboard", return_value=traders):
        stats = sync_top_traders(session, top_n=20)
    assert stats["added"] == 1
    assert stats["skipped_existing"] == 1
    assert stats["skipped_inactive"] == 1
    assert session.scalar(select(Source).where(Source.handle == "0x" + "a"*40)) is not None
    assert session.scalar(select(Source).where(Source.handle == "0x" + "c"*40)).active is False
