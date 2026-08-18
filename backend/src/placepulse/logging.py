from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}
_SENSITIVE_PARTS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "coordinate",
    "latitude",
    "longitude",
)


def _safe_field(name: str, value: Any) -> Any:
    if any(part in name.lower() for part in _SENSITIVE_PARTS):
        return "[REDACTED]"
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class JsonFormatter(logging.Formatter):
    def __init__(
        self,
        environment: str | None = None,
        service: str = "placepulse-api",
    ) -> None:
        super().__init__()
        self.environment = environment or os.getenv("PLACEPULSE_ENV", "local")
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "severity": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "event": getattr(record, "event", "application_log"),
            "logger": record.name,
        }
        request_id = request_id_context.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for name, value in record.__dict__.items():
            if name not in _RESERVED and name not in payload:
                payload[name] = _safe_field(name, value)
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def configure_logging(
    level: str,
    environment: str,
    service: str = "placepulse-api",
) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(environment, service))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
