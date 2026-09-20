"""Minimal JSON logging without request bodies or secrets."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from app.config import Settings


LOGGER_NAME = "personal_dev_assistant"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "trace_id": getattr(record, "trace_id", None),
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status": getattr(record, "status", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }
        return json.dumps({key: value for key, value in payload.items() if value is not None})


def configure_logging(settings: Settings) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    target = str(settings.logs_dir / "app.jsonl")
    if getattr(logger, "_pda_target", None) == target:
        return logger
    for existing in list(logger.handlers):
        existing.close()
        logger.removeHandler(existing)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    try:
        handler: logging.Handler = RotatingFileHandler(
            target,
            maxBytes=1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._pda_target = target  # type: ignore[attr-defined]
    return logger


def close_logging() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger._pda_target = None  # type: ignore[attr-defined]
