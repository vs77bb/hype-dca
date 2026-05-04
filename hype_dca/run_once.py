"""Run exactly one DCA cycle, then exit.

This is intended for external schedulers such as launchd or cron.
"""

import logging

from bot import run_dca


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


if __name__ == "__main__":
    run_dca()
