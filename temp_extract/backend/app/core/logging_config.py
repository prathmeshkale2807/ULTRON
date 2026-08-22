"""
Logging setup for ULTRON.

Phase 1 goal: every component logs to a rotating local file and to the
console, with a consistent format, so that later phases (audit logging,
verification results, permission decisions) all have a place to land.

This module deliberately does not log to any remote/cloud service --
per the architecture's privacy requirements, ULTRON's own operational
logs stay local by default.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.core.config import get_settings


def configure_logging() -> logging.Logger:
    settings = get_settings()
    settings.ensure_data_dirs()

    log_path = Path(settings.log_dir) / "ultron.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger("ultron")
    root_logger.setLevel(settings.log_level.upper())
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    root_logger.propagate = False
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the 'ultron' namespace."""
    return logging.getLogger(f"ultron.{name}")
