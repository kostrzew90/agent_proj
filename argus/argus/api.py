from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from argus.db import SessionLocal
from argus.models import Source, SourceScore, Claim, Outcome
from argus.analytics import trend_lean

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
    return trend_lean(session, horizon)

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

# static dashboard (created later in Task 12)
_web = Path(__file__).parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
