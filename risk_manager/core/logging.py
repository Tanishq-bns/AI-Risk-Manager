"""Structured application logging for AI Risk Manager.

Supports:
1. Standard library logging integration.
2. JSON structured formatting with UTC timestamps and correlation contexts.
3. Plain readable formatting for local development.
4. Redaction of sensitive fields / free-text PII per TRD.md §U.
"""

from datetime import datetime, timezone
import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formatter that outputs structured JSON log entries with trace correlation and PII scrubbing."""

    def format(self, record: logging.LogRecord) -> str:
        from risk_manager.observability.scrubber import scrub_data
        from risk_manager.observability.tracer import get_current_span_id, get_current_trace_id

        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "ai-risk-manager",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "caller": f"{record.filename}:{record.lineno}",
        }

        # Inject OpenTelemetry distributed trace context if available
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()
        if trace_id:
            log_entry["trace_id"] = trace_id
        if span_id:
            log_entry["span_id"] = span_id

        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Include custom context fields passed via extra={}
        context: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "module", "msecs",
                "message", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName",
            }:
                context[key] = value

        if context:
            log_entry["context"] = scrub_data(context)

        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
) -> None:
    """Configure root logger with structured formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )

    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Convenience getter for named loggers."""
    return logging.getLogger(name)
