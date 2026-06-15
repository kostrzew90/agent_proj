import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, case
from argus.db import SessionLocal
from argus.models import Source, SourceScore, SourceAssetScore, Claim, Outcome, Asset, WalletPosition, Liquidation, LlmCall, MacroData
from argus.analytics import trend_lean
from argus.scorer import argus_grade
from argus.charts import get_candles
from argus.hyperliquid import fetch_positions

app = FastAPI(title="Argus")

async def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/assets")
async def assets(horizon: str = "24h", session=Depends(get_session)):
    leans = {r["asset"]: r["lean"] for r in trend_lean(session, horizon)}
    rows = [{"asset": a.symbol, "kind": a.kind, "lean": leans.get(a.symbol, 0.0)}
            for a in session.scalars(select(Asset).where(Asset.scorable == True))]  # noqa: E712
    return sorted(rows, key=lambda r: -r["lean"])

@app.get("/api/sources")
async def sources(horizon: str = "24h", session=Depends(get_session)):
    rows = session.execute(
        select(Source, SourceScore)
        .join(SourceScore, SourceScore.source_id == Source.id)
        .where(SourceScore.horizon == horizon)
        .order_by(SourceScore.decayed_score.desc())
    ).all()
    return [{"display_name": s.display_name, "kind": s.kind,
             "n_claims": sc.n_claims, "hit_rate": sc.hit_rate,
             "avg_return": sc.avg_return, "decayed_score": sc.decayed_score}
            for s, sc in rows]

@app.get("/api/claims")
async def claims(limit: int = 50, session=Depends(get_session)):
    rows = session.scalars(select(Claim).order_by(Claim.entry_ts.desc()).limit(limit))
    return [{"id": c.id, "asset": c.asset, "direction": c.direction,
             "confidence": c.confidence, "method": c.method,
             "entry_ts": c.entry_ts.isoformat(), "status": c.status} for c in rows]

@app.get("/api/candles")
def candles(asset: str, session=Depends(get_session)):
    a = session.get(Asset, asset)
    if a is None:
        raise HTTPException(status_code=404, detail="unknown asset")
    try:
        return get_candles(a)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"candle fetch failed: {e}")

@app.get("/api/asset/{symbol}")
async def asset_detail(symbol: str, horizon: str = "1h", session=Depends(get_session)):
    claim_rows = session.execute(
        select(Claim, Source.display_name)
        .join(Source, Source.id == Claim.source_id)
        .where(Claim.asset == symbol)
        .order_by(Claim.entry_ts.desc()).limit(200)
    ).all()
    outcomes = {o.claim_id: o for o in session.scalars(
        select(Outcome).where(Outcome.horizon == horizon))}
    claims = []
    for c, sname in claim_rows:
        o = outcomes.get(c.id)
        claims.append({"id": c.id, "source": sname, "direction": c.direction,
                       "confidence": c.confidence, "entry_ts": c.entry_ts.isoformat(),
                       "entry_price": c.entry_price,
                       "hit": (o.hit if o else None),
                       "return_pct": (o.return_pct if o else None)})
    src_rows = session.execute(
        select(Source.display_name, SourceAssetScore)
        .join(SourceAssetScore, SourceAssetScore.source_id == Source.id)
        .where(SourceAssetScore.asset == symbol, SourceAssetScore.horizon == horizon)
        .order_by(SourceAssetScore.decayed_score.desc())
    ).all()
    sources = [{"display_name": n, "n_claims": s.n_claims, "hit_rate": s.hit_rate,
                "decayed_score": s.decayed_score} for n, s in src_rows]
    return {"claims": claims, "sources": sources}

_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")

@app.get("/api/wallets")
async def wallets(session=Depends(get_session)):
    out = []
    for src in session.scalars(select(Source).where(Source.kind == "hyperliquid")):
        score_rows = {sc.horizon: sc for sc in session.scalars(
            select(SourceScore).where(SourceScore.source_id == src.id))}
        active = session.scalar(select(func.count()).select_from(WalletPosition).where(
            WalletPosition.source_id == src.id, WalletPosition.open == True)) or 0  # noqa: E712
        # pick best horizon for argus grade: 24h preferred, fallback 7d → 1h
        sc = score_rows.get("24h") or score_rows.get("7d") or score_rows.get("1h")
        grade = argus_grade(sc.decayed_score, sc.n_claims) if sc else "?"
        out.append({"id": src.id, "display_name": src.display_name, "handle": src.handle,
                    "active": src.active,
                    "argus_grade": grade,
                    "acc_24h": score_rows["24h"].hit_rate if "24h" in score_rows else None,
                    "acc_7d":  score_rows["7d"].hit_rate  if "7d"  in score_rows else None,
                    "acc_30d": score_rows["30d"].hit_rate if "30d" in score_rows else None,
                    "active_positions": active})
    return out

@app.get("/api/wallets/preview")
def wallet_preview(address: str):
    if not _ADDR.match(address):
        raise HTTPException(status_code=422, detail="invalid address format")
    try:
        data = fetch_positions(address)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"cannot fetch positions: {e}")
    return {"address": address, "equity": data["equity"],
            "positions": [{"coin": p["coin"], "side": p["side"], "position_value": p["position_value"]}
                          for p in data["positions"]]}

@app.post("/api/wallets")
async def add_wallet(payload: dict, session=Depends(get_session)):
    address = (payload.get("address") or "").strip()
    if not _ADDR.match(address):
        raise HTTPException(status_code=422, detail="invalid address format")
    label = (payload.get("label") or address[:10]).strip()
    if session.scalar(select(Source).where(Source.handle == address)) is None:
        session.add(Source(kind="hyperliquid", handle=address, display_name=label, active=True))
        session.commit()
    return {"status": "ok", "address": address}

@app.post("/api/wallets/{wallet_id}/deactivate")
async def deactivate_wallet(wallet_id: int, session=Depends(get_session)):
    src = session.get(Source, wallet_id)
    if src is None:
        raise HTTPException(status_code=404, detail="unknown wallet")
    src.active = False
    session.commit()
    return {"status": "ok"}

_LIQ_WINDOWS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4),
                "24h": timedelta(hours=24), "7d": timedelta(days=7)}

@app.get("/api/liquidations")
async def liquidations(window: str = "24h", session=Depends(get_session)):
    since = datetime.now(timezone.utc) - _LIQ_WINDOWS.get(window, _LIQ_WINDOWS["24h"])
    rows = session.execute(
        select(Liquidation.asset, Liquidation.side,
               func.sum(Liquidation.notional_usd), func.count())
        .where(Liquidation.ts >= since)
        .group_by(Liquidation.asset, Liquidation.side)).all()
    agg: dict = {}
    for asset, side, usd, n in rows:
        a = agg.setdefault(asset, {"asset": asset, "long_liq_usd": 0.0, "short_liq_usd": 0.0, "count": 0})
        a["long_liq_usd" if side == "long_liq" else "short_liq_usd"] = float(usd or 0)
        a["count"] += int(n)
    return sorted(agg.values(), key=lambda r: -(r["long_liq_usd"] + r["short_liq_usd"]))

@app.get("/api/liquidations/largest")
async def liquidations_largest(window: str = "24h", min_notional: float = 100000.0,
                               session=Depends(get_session)):
    since = datetime.now(timezone.utc) - _LIQ_WINDOWS.get(window, _LIQ_WINDOWS["24h"])
    rows = session.scalars(
        select(Liquidation).where(Liquidation.ts >= since,
                                  Liquidation.notional_usd >= min_notional)
        .order_by(Liquidation.notional_usd.desc()).limit(50))
    return [{"asset": l.asset, "side": l.side, "notional_usd": l.notional_usd,
             "price": l.price, "ts": l.ts.isoformat()} for l in rows]

@app.get("/api/llm/usage")
async def llm_usage(window: str = "24h", session=Depends(get_session)):
    since = datetime.now(timezone.utc) - _LIQ_WINDOWS.get(window, _LIQ_WINDOWS["24h"])
    ok_sum = func.sum(case((LlmCall.ok == True, 1), else_=0))  # noqa: E712
    rows = session.execute(
        select(LlmCall.provider, LlmCall.model, func.count(), ok_sum,
               func.sum(LlmCall.tokens_in), func.sum(LlmCall.tokens_out),
               func.sum(LlmCall.cost_usd), func.avg(LlmCall.latency_ms))
        .where(LlmCall.ts >= since)
        .group_by(LlmCall.provider, LlmCall.model)).all()
    return sorted(
        [{"provider": p, "model": m, "calls": int(c), "ok": int(ok or 0),
          "tokens_in": int(ti or 0), "tokens_out": int(to or 0),
          "cost_usd": round(float(cost or 0), 6), "avg_latency_ms": int(lat or 0)}
         for p, m, c, ok, ti, to, cost, lat in rows],
        key=lambda r: -r["calls"])

@app.get("/api/macro")
async def macro(session=Depends(get_session)):
    from argus.collectors.fred import get_latest_macro, macro_regime_score
    latest = get_latest_macro(session)
    regime = macro_regime_score(latest)
    if regime > 0.25:    label = "risk-on"
    elif regime < -0.25: label = "risk-off"
    else:                label = "neutral"
    return {"series": latest, "regime": round(regime, 3), "regime_label": label}

# static dashboard (created later in Task 12)
_web = Path(__file__).parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
