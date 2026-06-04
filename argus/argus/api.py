from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from argus.db import SessionLocal
from argus.models import Source, SourceScore, SourceAssetScore, Claim, Outcome, Asset
from argus.analytics import trend_lean
from argus.charts import get_candles

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

# static dashboard (created later in Task 12)
_web = Path(__file__).parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
