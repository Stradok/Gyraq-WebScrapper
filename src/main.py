import logging
import sys

from . import config
from .queue_runner import run_forever


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    setup_logging()
    log = logging.getLogger("main")
    log.info("Starting Google Maps scraper service")
    log.info("queries_file=%s results_dir=%s", config.QUERIES_FILE, config.RESULTS_DIR)
    try:
        run_forever()
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down.")


if __name__ == "__main__":
    main()
