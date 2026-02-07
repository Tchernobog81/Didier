import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logging(log_path="logs/didier.log"):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logger = logging.getLogger("didier")
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
    fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger
