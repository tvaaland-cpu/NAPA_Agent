from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler


def build_scheduler() -> BlockingScheduler:
    return BlockingScheduler(timezone="Europe/Oslo")
