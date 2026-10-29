"""A small rotating log in the data folder, so problems on a real setup can be diagnosed."""
import logging
import logging.handlers

from .config import DATA_DIR

LOG_PATH = DATA_DIR / "metalmate.log"


def get_logger() -> logging.Logger:
    log = logging.getLogger("metalmate")
    if not log.handlers:
        handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    return log
