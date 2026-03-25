"""
APScheduler Integration

Zarządza zadaniami cyklicznymi dla trading agenta.
"""
import logging
from typing import Callable, Dict, Optional, List
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from config import config

logger = logging.getLogger(__name__)


class TradingScheduler:
    """
    Scheduler for trading tasks

    Tasks:
    - collect_market_data: 1 min - Pobieranie cen i funding rate
    - generate_signals: 5 min - Generowanie sygnałów tradingowych
    - monitor_positions: 30 sec - Monitorowanie pozycji (SL/TP)
    - check_risk: 1 min - Kontrola limitów ryzyka
    - scan_liquidity: 15 min - Skanowanie poziomów liquidity
    - daily_report: 00:00 - Dzienny raport
    """

    def __init__(self):
        self.scheduler = BackgroundScheduler(
            timezone="UTC",
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 30
            }
        )
        self.cfg = config.scheduler
        self._jobs: Dict[str, dict] = {}

        # Event listeners
        self.scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED
        )
        self.scheduler.add_listener(
            self._on_job_error,
            EVENT_JOB_ERROR
        )

    def _on_job_executed(self, event):
        """Handle successful job execution"""
        job_id = event.job_id
        if job_id in self._jobs:
            self._jobs[job_id]["last_run"] = datetime.now()
            self._jobs[job_id]["run_count"] = self._jobs[job_id].get("run_count", 0) + 1

    def _on_job_error(self, event):
        """Handle job error"""
        job_id = event.job_id
        logger.error(f"Job {job_id} failed: {event.exception}")
        if job_id in self._jobs:
            self._jobs[job_id]["last_error"] = str(event.exception)
            self._jobs[job_id]["error_count"] = self._jobs[job_id].get("error_count", 0) + 1

    def add_interval_job(self, job_id: str, func: Callable,
                         seconds: int, description: str = "",
                         start_now: bool = True):
        """
        Add interval-based job

        Args:
            job_id: Unique job identifier
            func: Function to execute
            seconds: Interval in seconds
            description: Job description
            start_now: Execute immediately on start
        """
        trigger = IntervalTrigger(seconds=seconds)

        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=description or job_id,
            replace_existing=True
        )

        self._jobs[job_id] = {
            "description": description,
            "interval_seconds": seconds,
            "status": "scheduled",
            "last_run": None,
            "run_count": 0,
            "error_count": 0
        }

        if start_now:
            self.run_job_now(job_id)

    def add_cron_job(self, job_id: str, func: Callable,
                     hour: int = 0, minute: int = 0,
                     description: str = ""):
        """
        Add cron-based job (daily at specific time)

        Args:
            job_id: Unique job identifier
            func: Function to execute
            hour: Hour (0-23)
            minute: Minute (0-59)
            description: Job description
        """
        trigger = CronTrigger(hour=hour, minute=minute)

        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=description or job_id,
            replace_existing=True
        )

        self._jobs[job_id] = {
            "description": description,
            "schedule": f"{hour:02d}:{minute:02d} UTC",
            "status": "scheduled",
            "last_run": None,
            "run_count": 0,
            "error_count": 0
        }

    def remove_job(self, job_id: str):
        """Remove job"""
        try:
            self.scheduler.remove_job(job_id)
            if job_id in self._jobs:
                del self._jobs[job_id]
        except Exception as e:
            logger.warning(f"Failed to remove job {job_id}: {e}")

    def pause_job(self, job_id: str):
        """Pause job"""
        try:
            self.scheduler.pause_job(job_id)
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "paused"
        except Exception as e:
            logger.warning(f"Failed to pause job {job_id}: {e}")

    def resume_job(self, job_id: str):
        """Resume paused job"""
        try:
            self.scheduler.resume_job(job_id)
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "scheduled"
        except Exception as e:
            logger.warning(f"Failed to resume job {job_id}: {e}")

    def run_job_now(self, job_id: str):
        """Execute job immediately"""
        job = self.scheduler.get_job(job_id)
        if job:
            job.func()

    def start(self):
        """Start scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")

    def stop(self):
        """Stop scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def pause_all(self):
        """Pause all jobs"""
        self.scheduler.pause()
        for job_id in self._jobs:
            self._jobs[job_id]["status"] = "paused"

    def resume_all(self):
        """Resume all jobs"""
        self.scheduler.resume()
        for job_id in self._jobs:
            self._jobs[job_id]["status"] = "scheduled"

    def get_jobs_status(self) -> Dict[str, dict]:
        """Get status of all jobs"""
        result = {}

        for job_id, info in self._jobs.items():
            job = self.scheduler.get_job(job_id)
            next_run = None

            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

            result[job_id] = {
                **info,
                "next_run": next_run,
                "is_running": job is not None
            }

        return result

    def get_job_info(self, job_id: str) -> Optional[dict]:
        """Get info about specific job"""
        return self._jobs.get(job_id)

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self.scheduler.running


def create_trading_scheduler() -> TradingScheduler:
    """Create and configure trading scheduler with default jobs"""
    scheduler = TradingScheduler()

    # Import task functions (will be created in tasks/ module)
    # For now, use placeholder functions
    def placeholder():
        pass

    # Add default jobs (will be connected to actual tasks later)
    scheduler.add_interval_job(
        "collect_market_data",
        placeholder,
        seconds=config.scheduler.market_data_interval,
        description="Collect market data from GATE.io"
    )

    scheduler.add_interval_job(
        "generate_signals",
        placeholder,
        seconds=config.scheduler.signals_interval,
        description="Generate trading signals"
    )

    scheduler.add_interval_job(
        "monitor_positions",
        placeholder,
        seconds=config.scheduler.monitor_interval,
        description="Monitor open positions for SL/TP"
    )

    scheduler.add_interval_job(
        "check_risk",
        placeholder,
        seconds=config.scheduler.risk_check_interval,
        description="Check risk limits"
    )

    scheduler.add_interval_job(
        "scan_liquidity",
        placeholder,
        seconds=config.scheduler.liquidity_scan_interval,
        description="Scan for liquidity levels"
    )

    scheduler.add_cron_job(
        "daily_report",
        placeholder,
        hour=0,
        minute=0,
        description="Generate daily trading report"
    )

    return scheduler
