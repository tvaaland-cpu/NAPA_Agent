from __future__ import annotations

import logging

from napa_agent.config import get_settings
from napa_agent.db import get_engine, init_db
from napa_agent.pipelines.daily_monitor import run_daily_monitor
from napa_agent.pipelines.rumor_sweep import run_rumor_sweep
from napa_agent.pipelines.shareholders import shareholders_check
from napa_agent.scheduler import build_scheduler
from napa_agent.util.logging import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    engine = get_engine(settings.database_url)
    init_db(engine)

    scheduler = build_scheduler()
    scheduler.add_job(run_daily_monitor, "cron", hour=7, minute=10, args=[engine, settings], id="daily_monitor")
    scheduler.add_job(
        shareholders_check,
        "cron",
        day_of_week="mon",
        hour=13,
        minute=0,
        args=[engine, settings],
        kwargs={"attempt": 13, "scheduler": scheduler},
        id="monday_top20_13",
    )
    scheduler.add_job(run_rumor_sweep, "cron", hour="*/4", args=[engine, settings], id="rumor_sweep")

    logger.info("Starting scheduler with Europe/Oslo timezone")
    scheduler.start()


if __name__ == "__main__":
    main()
