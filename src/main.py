import logging
import sys
import threading

import uvicorn

from . import config
from .api import app
from .auth import get_or_create_token
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
    log.info("API listening on %s:%d", config.API_HOST, config.API_PORT)
    token = get_or_create_token()
    log.info(
        "Access token (the desktop app reads this automatically; a plain "
        "browser needs it once): %s",
        token,
    )

    worker = threading.Thread(target=run_forever, daemon=True, name="scraper-worker")
    worker.start()

    try:
        uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level=config.LOG_LEVEL.lower())
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down.")


if __name__ == "__main__":
    main()
