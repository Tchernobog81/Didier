import logging
from logging.handlers import RotatingFileHandler
import os

def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def setup_logging(log_path: str = "logs/didier.log"):
    log_dir = os.path.dirname(log_path) or "logs"
    os.makedirs(log_dir, exist_ok=True)
    level = os.getenv("DIDIER_LOG_LEVEL", "INFO").upper()
    rotate_mb = _get_int_env("DIDIER_LOG_ROTATE_MB", 25)
    backup_count = _get_int_env("DIDIER_LOG_BACKUPS", 14)
    max_bytes = max(1, rotate_mb) * 1024 * 1024

    logger = logging.getLogger("didier")
    if logger.handlers:
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    fh = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
