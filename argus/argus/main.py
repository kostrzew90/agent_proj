import os
import uvicorn
from argus.db import Base, engine, SessionLocal
import argus.models  # noqa
from argus.config import settings
from argus.seed import seed_assets, seed_sources
from argus.collectors.rss import collect_rss
from argus.collectors.hyperliquid import collect_wallet, compute_consensus
from argus.evaluator import evaluate_due_claims
from argus.scorer import recompute_scores
from argus.scheduler.apscheduler_impl import APScheduler
from argus.models import Source
from sqlalchemy import select
from datetime import datetime, timezone

def _rss_job():
    with SessionLocal() as s:
        for src in s.scalars(select(Source).where(Source.kind == "rss", Source.active == True)):  # noqa: E712
            collect_rss(s, src)

def _eval_job():
    with SessionLocal() as s:
        evaluate_due_claims(s, datetime.now(timezone.utc))

def _score_job():
    with SessionLocal() as s:
        recompute_scores(s)

def _hyperliquid_job():
    from argus.models import Source
    with SessionLocal() as s:
        for src in s.scalars(select(Source).where(Source.kind == "hyperliquid", Source.active == True)):  # noqa: E712
            try:
                collect_wallet(s, src)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("HL collect failed %s: %s", src.handle, e)
        compute_consensus(s)

def bootstrap():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_assets(s, settings.watchlist_path)
        seed_sources(s, settings.sources_path)
        if os.path.exists("config/wallets.yaml"):
            seed_sources(s, "config/wallets.yaml")
    sched = APScheduler()
    sched.add_interval("rss", _rss_job, minutes=30)
    sched.add_interval("evaluate", _eval_job, minutes=60)
    sched.add_interval("score", _score_job, minutes=360)
    sched.add_interval("hyperliquid", _hyperliquid_job, minutes=15)
    sched.start()

if __name__ == "__main__":
    bootstrap()
    uvicorn.run("argus.api:app", host="0.0.0.0", port=8080)
