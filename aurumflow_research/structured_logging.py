"""Per-run JSON Lines logging without global logging configuration."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", None),
            "experiment_id": getattr(record, "experiment_id", None),
            "research_object": getattr(record, "research_object", None),
            "event": getattr(record, "event", None),
            "fields": getattr(record, "fields", {}),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


class RunLogger:
    def __init__(
        self,
        *,
        path: Path,
        level: str,
        console: bool,
        run_id: str,
        experiment_id: str,
        research_object: str,
    ) -> None:
        self._context = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "research_object": research_object,
        }
        self._logger = logging.getLogger(f"aurumflow_research.{run_id}")
        self._logger.setLevel(level)
        self._logger.propagate = False
        self._logger.handlers.clear()
        formatter = JsonLineFormatter()

        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)
        if console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)

    def log(self, level: int, event: str, message: str, **fields: Any) -> None:
        self._logger.log(
            level,
            message,
            extra={**self._context, "event": event, "fields": fields},
        )

    def debug(self, event: str, message: str, **fields: Any) -> None:
        self.log(logging.DEBUG, event, message, **fields)

    def info(self, event: str, message: str, **fields: Any) -> None:
        self.log(logging.INFO, event, message, **fields)

    def warning(self, event: str, message: str, **fields: Any) -> None:
        self.log(logging.WARNING, event, message, **fields)

    def error(self, event: str, message: str, **fields: Any) -> None:
        self.log(logging.ERROR, event, message, **fields)

    def exception(self, event: str, message: str, **fields: Any) -> None:
        self._logger.exception(
            message,
            extra={**self._context, "event": event, "fields": fields},
        )

    def close(self) -> None:
        for handler in list(self._logger.handlers):
            handler.flush()
            handler.close()
            self._logger.removeHandler(handler)
