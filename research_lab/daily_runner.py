from __future__ import annotations

import logging
import time

from .config import load_config
from .daily_comparison import DailyComparisonLab


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("research_lab.daily_runner")


def main() -> None:
    config = load_config()
    lab = DailyComparisonLab(config)
    interval = 300
    LOG.info("Daily comparison runner started")
    while True:
        try:
            results = lab.run_due(send_telegram=True)
            if results:
                LOG.info("daily reports generated=%s", [result.result_id for result in results])
        except Exception as exc:
            LOG.exception("DAILY_COMPARISON_FAILED: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
