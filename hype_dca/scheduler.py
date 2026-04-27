"""Entrypoint: runs run_dca() immediately, then every hour."""

import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from bot import run_dca

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    # next_run_time=datetime.now() fires immediately on start, then hourly
    scheduler.add_job(run_dca, "interval", hours=1, next_run_time=datetime.now())
    scheduler.start()
