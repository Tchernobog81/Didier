import logging
import logging.config
from pathlib import Path


def setup_logging(log_dir: str = "logs", level: str = "INFO") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / "didier.log"

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level,
                },
                "file": {
                    "class": "logging.FileHandler",
                    "formatter": "default",
                    "level": level,
                    "filename": str(log_path),
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": level,
            },
        }
    )
