"""
LifeData V4 — Parser Utilities
core/parser_utils.py

Standardized per-row error handling for CSV parsers. Provides
safe_parse_rows() so every module's parser doesn't independently
reinvent the try/except-per-line + quarantine pattern.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from core.event import Event
from core.logger import get_logger
from core.sanitizer import sanitize_for_log

log = get_logger("lifedata.parser_utils")

# Files with more than this fraction of rows skipped are quarantined
QUARANTINE_THRESHOLD = 0.50

# Maximum length of raw line content logged on error
MAX_LINE_LOG_LEN = 200


@dataclass
class ParseResult:
    """Result of parsing a single file with safe_parse_rows."""

    events: list[Event] = field(default_factory=list)
    skipped: int = 0
    total_rows: int = 0
    quarantined: bool = False
    filepath: str = ""


def safe_parse_rows(
    filepath: str,
    parse_fn: Callable[[list[str], int], Event | list[Event] | None],
    module_id: str,
) -> ParseResult:
    """Iterate rows of a CSV file with per-row error handling.

    For each non-blank row, splits on commas and calls parse_fn(fields, line_num).
    parse_fn should return an Event, a list of Events, or None (to skip the row).
    Exceptions from parse_fn are caught, logged, and counted as skips.

    After parsing, if more than 50% of rows were skipped, the file is
    flagged as quarantined and a WARNING is logged.

    Args:
        filepath: Path to the CSV file.
        parse_fn: Callable(fields: list[str], line_num: int) -> Event | list[Event] | None.
                  Receives the split CSV fields and 1-based line number.
        module_id: Module identifier for log messages (e.g. "device").

    Returns:
        ParseResult with events, skip count, total rows, and quarantine flag.
    """
    result = ParseResult(filepath=filepath)

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line_num, raw_line in enumerate(f, 1):
                line = raw_line.strip()
                if not line:
                    continue

                result.total_rows += 1
                # NOTE: Intentional use of str.split(",") instead of csv.reader.
                # Tasker-generated CSVs do not use RFC 4180 quoting — fields
                # never contain commas. See CLAUDE.md Design Rules.
                fields = line.split(",")

                try:
                    parsed = parse_fn(fields, line_num)
                    if parsed is None:
                        # Intentional skip (e.g. non-epoch header line)
                        continue
                    # Stamp provenance on every returned event
                    basename = os.path.basename(filepath)
                    events_to_stamp = parsed if isinstance(parsed, list) else [parsed]
                    for evt in events_to_stamp:
                        ver = evt.parser_version or "?"
                        evt.provenance = (
                            f"file={basename}:line={line_num}"
                            f":parser={module_id}:v={ver}"
                        )
                    if isinstance(parsed, list):
                        result.events.extend(parsed)
                    else:
                        result.events.append(parsed)
                except Exception as e:
                    result.skipped += 1
                    truncated = sanitize_for_log(line[:MAX_LINE_LOG_LEN])
                    log.warning(
                        f"[{module_id}] {filepath}:{line_num}: "
                        f"parse error: {e} — raw: {truncated!r}"
                    )
    except OSError as e:
        log.error(f"[{module_id}] Could not read {filepath}: {e}")
        return result

    # Quarantine check: >50% of rows skipped
    if result.total_rows > 0 and (result.skipped / result.total_rows) > QUARANTINE_THRESHOLD:
        result.quarantined = True
        log.warning(
            f"[{module_id}] QUARANTINED {filepath}: "
            f"{result.skipped}/{result.total_rows} rows skipped "
            f"({result.skipped / result.total_rows * 100:.0f}%)"
        )

    return result
