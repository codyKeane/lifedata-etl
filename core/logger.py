"""
LifeData V4 — Structured Logging
core/logger.py

Provides JSON-structured file logging (machine-parseable) and human-readable
console logging. Sanitizes messages to prevent newline injection attacks.
"""

import contextlib
import json
import logging
import os
import re
from datetime import UTC, datetime

# Compiled once — used to strip embedded newlines from log messages.
# Prevents log injection attacks from malformed CSV data.
_NEWLINE_RE = re.compile(r"[\r\n]+")


class StructuredFormatter(logging.Formatter):
    """Outputs JSON-lines for machine-parseable logs.

    Sanitizes messages to prevent newline injection attacks where
    embedded newlines in data (e.g., CSV fields) could corrupt
    the structured log format.
    """

    def format(self, record: logging.LogRecord) -> str:
        msg = _NEWLINE_RE.sub(" ", record.getMessage())
        log_entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "msg": msg,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    log_path: str,
    level: str = "INFO",
    name: str = "lifedata",
) -> logging.Logger:
    """Configure logging for the LifeData ETL system.

    Args:
        log_path: Path to the structured JSON log file.
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        name: Logger name (default: 'lifedata').

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    # Prevent duplicate handlers if setup_logging is called multiple times
    # (e.g., in tests or when re-running the ETL).
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Ensure log directory exists
    expanded_path = os.path.expanduser(log_path)
    os.makedirs(os.path.dirname(expanded_path), exist_ok=True)

    # File handler: structured JSON-lines
    fh = logging.FileHandler(expanded_path, encoding="utf-8")
    fh.setFormatter(StructuredFormatter())
    logger.addHandler(fh)

    # Restrict log file permissions — logs may contain sensitive data paths
    with contextlib.suppress(OSError):
        os.chmod(expanded_path, 0o600)

    # Console handler: human-readable
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(ch)

    return logger


def get_logger(name: str = "lifedata") -> logging.Logger:
    """Get or create a child logger under the lifedata namespace.

    Usage from modules:
        from core.logger import get_logger
        log = get_logger(__name__)
    """
    return logging.getLogger(name)
