from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler
from argus.scheduler.base import Scheduler

class APScheduler(Scheduler):
    def __init__(self):
        self._sched = BackgroundScheduler(timezone="UTC")
        self._fns: dict[str, Callable[[], None]] = {}

    def add_interval(self, name, fn, *, minutes):
        self._fns[name] = fn
        self._sched.add_job(fn, "interval", minutes=minutes, id=name, replace_existing=True)

    def list_jobs(self):
        return list(self._fns.keys())

    def run_now(self, name):
        self._fns[name]()

    def start(self):
        self._sched.start()
