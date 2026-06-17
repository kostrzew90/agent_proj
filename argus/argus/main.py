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
from argus.liquidations.cleanup import prune_liquidations
from argus.scheduler.apscheduler_impl import APScheduler
from argus.models import Source, Asset
from argus.collectors.hyperstats import sync_top_traders
from sqlalchemy import select
from datetime import datetime, timezone

def _rss_job():
    with SessionLocal() as s:
        for src in s.scalars(select(Source).where(
                Source.kind.in_(["rss", "reddit", "news"]), Source.active == True)):  # noqa: E712
            collect_rss(s, src)


def _llm_batch_job():
    from argus.llm.batch import process_llm_batch
    from argus.collectors.rss import load_sector_map
    batch_size = int(os.getenv("ARGUS_LLM_BATCH_SIZE", "8"))
    with SessionLocal() as s:
        assets = list(s.scalars(select(Asset).where(Asset.scorable == True)))  # noqa: E712
        sector_map = load_sector_map()
        stats = process_llm_batch(s, batch_size, assets, sector_map)
    import logging
    logging.getLogger(__name__).info("llm_batch: %s", stats)

def _eval_job():
    with SessionLocal() as s:
        evaluate_due_claims(s, datetime.now(timezone.utc))

def _score_job():
    with SessionLocal() as s:
        recompute_scores(s)
        prune_liquidations(s)

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

def _insider_job():
    from argus.collectors.insider import collect_insider, _EXCHANGE
    from argus.models import Asset
    with SessionLocal() as s:
        stocks = list(s.scalars(
            select(Asset).where(Asset.kind == "stock", Asset.scorable == True)  # noqa: E712
        ))
        for asset in stocks:
            if asset.symbol not in _EXCHANGE:
                continue
            src = s.scalar(select(Source).where(
                Source.kind == "insider", Source.handle == f"insider:{asset.symbol}"
            ))
            if src is None:
                src = Source(kind="insider", handle=f"insider:{asset.symbol}",
                             display_name=f"{asset.symbol} Insiders", active=True)
                s.add(src); s.commit(); s.refresh(src)
            try:
                collect_insider(s, src, asset.symbol, asset)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("insider job failed %s: %s", asset.symbol, e)

def _fred_job():
    import os
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        import logging; logging.getLogger(__name__).warning("FRED_API_KEY not set — skipping")
        return
    from argus.collectors.fred import collect_fred
    with SessionLocal() as s:
        collect_fred(s, api_key=api_key, lookback=24)

def _edgar_job():
    from argus.collectors.edgar import collect_edgar_insider, get_cik
    from argus.models import Asset
    with SessionLocal() as s:
        stocks = list(s.scalars(
            select(Asset).where(Asset.kind == "stock", Asset.scorable == True)  # noqa: E712
        ))
        for asset in stocks:
            cik = get_cik(asset.symbol)
            if cik is None:
                continue
            src = s.scalar(select(Source).where(
                Source.kind == "edgar", Source.handle == f"edgar:{asset.symbol}"
            ))
            if src is None:
                src = Source(kind="edgar", handle=f"edgar:{asset.symbol}",
                             display_name=f"{asset.symbol} SEC Form4", active=True)
                s.add(src); s.commit(); s.refresh(src)
            try:
                collect_edgar_insider(s, src, asset.symbol, cik, asset)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("edgar job failed %s: %s", asset.symbol, e)

def _hyperstats_job():
    import os
    with SessionLocal() as s:
        try:
            sync_top_traders(
                s,
                top_n=int(os.getenv("ARGUS_HYPERSTATS_TOP_N", "20")),
                min_win_rate=float(os.getenv("ARGUS_HYPERSTATS_MIN_WINRATE", "0.5")),
                min_trades=int(os.getenv("ARGUS_HYPERSTATS_MIN_TRADES", "50")),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("hyperstats job failed: %s", e)

def bootstrap():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_assets(s, settings.watchlist_path)
        seed_sources(s, settings.sources_path)
        if os.path.exists("config/wallets.yaml"):
            seed_sources(s, "config/wallets.yaml")
    sched = APScheduler()
    sched.add_interval("rss", _rss_job, minutes=30)
    sched.add_interval("llm_batch", _llm_batch_job, minutes=120)
    sched.add_interval("evaluate", _eval_job, minutes=60)
    sched.add_interval("score", _score_job, minutes=360)
    sched.add_interval("hyperliquid", _hyperliquid_job, minutes=15)
    sched.add_interval("hyperstats", _hyperstats_job, minutes=1440)
    sched.add_interval("insider", _insider_job, minutes=720)
    sched.add_interval("fred", _fred_job, minutes=1440)
    sched.add_interval("edgar", _edgar_job, minutes=360)
    sched.start()

if __name__ == "__main__":
    bootstrap()
    uvicorn.run("argus.api:app", host="0.0.0.0", port=8080)
