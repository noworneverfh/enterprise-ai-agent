from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import BACKEND_DIR


LOG_DIR = BACKEND_DIR / "logs"


def configure_logging() -> None:
    """Configure application logging for local and Docker deployments."""

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    if not any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    _add_rotating_file_handler(root_logger, LOG_DIR / "app.log", formatter)
    _add_named_logger("request", LOG_DIR / "request.log", formatter)
    _add_named_logger("agent", LOG_DIR / "agent.log", formatter)


def _add_named_logger(name: str, path, formatter: logging.Formatter) -> None:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = True
    _add_rotating_file_handler(logger, path, formatter)


def _add_rotating_file_handler(
    logger: logging.Logger,
    path,
    formatter: logging.Formatter,
) -> None:
    resolved = str(path)
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == resolved:
            return

    file_handler = RotatingFileHandler(
        resolved,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
