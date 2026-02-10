import logging
import logging.config
import os
from pathlib import Path


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def setup_logging(log_dir: str | None = None, level: str | None = None) -> None:
    log_dir = log_dir or os.getenv("DIDIER_LOG_DIR", "logs")
    level = str(level or os.getenv("DIDIER_LOG_LEVEL", "INFO")).upper()
    rotate_mb = _get_int_env("DIDIER_LOG_ROTATE_MB", 25)
    backup_count = _get_int_env("DIDIER_LOG_BACKUPS", 14)
    max_bytes = max(1, rotate_mb) * 1024 * 1024

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    log_path = log_dir_path / "didier.log"
    audio_path = log_dir_path / "didier-audio.log"
    vision_path = log_dir_path / "didier-vision.log"

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
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": level,
                    "filename": str(log_path),
                    "maxBytes": max_bytes,
                    "backupCount": backup_count,
                    "encoding": "utf-8",
                },
                "audio_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": level,
                    "filename": str(audio_path),
                    "maxBytes": max_bytes,
                    "backupCount": backup_count,
                    "encoding": "utf-8",
                },
                "vision_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "level": level,
                    "filename": str(vision_path),
                    "maxBytes": max_bytes,
                    "backupCount": backup_count,
                    "encoding": "utf-8",
                },
            },
            "loggers": {
                "Tentacle.hearing": {
                    "handlers": ["console", "file", "audio_file"],
                    "level": level,
                    "propagate": False,
                },
                "Tentacle.vocal": {
                    "handlers": ["console", "file", "audio_file"],
                    "level": level,
                    "propagate": False,
                },
                "Tentacle.music": {
                    "handlers": ["console", "file", "audio_file"],
                    "level": level,
                    "propagate": False,
                },
                "Tentacle.vision": {
                    "handlers": ["console", "file", "vision_file"],
                    "level": level,
                    "propagate": False,
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": level,
            },
        }
    )
