"""python -m hira_alert : 한 번 실행한다 (cron용)."""

import logging
import sys

from .config import Settings
from .runner import run


def main() -> int:
    settings = Settings.from_env()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(settings.log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
