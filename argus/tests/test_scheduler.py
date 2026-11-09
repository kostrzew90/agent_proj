from argus.scheduler.apscheduler_impl import APScheduler

def test_register_and_list_jobs():
    sched = APScheduler()
    sched.add_interval("rss", lambda: None, minutes=30)
    sched.add_interval("evaluate", lambda: None, minutes=60)
    assert set(sched.list_jobs()) == {"rss", "evaluate"}

def test_run_now_executes():
    calls = []
    sched = APScheduler()
    sched.add_interval("x", lambda: calls.append(1), minutes=5)
    sched.run_now("x")
    assert calls == [1]
