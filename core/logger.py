import logging
import os
from logging.handlers import RotatingFileHandler
from .constants import LOG_DIR, APP_NAME

def get_logger(name: str = APP_NAME) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    ch.setFormatter(ch_formatter)
    logger.addHandler(ch)

    # File handler
    os.makedirs(LOG_DIR, exist_ok=True)
    # Each app process owns its log file. Multiple tool instances can run at the
    # same time on Windows, where rotating one shared file would fight file locks.
    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, f"{APP_NAME}-{os.getpid()}.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
    )
    fh.setFormatter(fh_formatter)
    logger.addHandler(fh)

    return logger

log = get_logger()
