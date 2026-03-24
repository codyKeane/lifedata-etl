"""
LifeData V4 — Meta Module: Data Quality Validators
modules/meta/quality.py

Catches data quality issues: future timestamps, out-of-range values,
suspicious duplicates, and time gaps in periodic sources.
"""

from core.logger import get_logger

log = get_logger("lifedata.meta.quality")

# Numeric range checks: source_module → (min_value, max_value)
NUMERIC_RANGES = {
    "mind.mood": (1.0, 10.0),
    "mind.stress": (1.0, 10.0),
    "mind.energy": (1.0, 10.0),
    "mind.sleep": (1.0, 10.0),
    "mind.productivity": (1.0, 10.0),
    "mind.social_satisfaction": (1.0, 10.0),
    "device.battery": (0.0, 100.0),
}

# Periodic sources: source_module → expected_interval_minutes
PERIODIC_SOURCES = {
    "device.battery": 15,
    "environment.location": 5,
}


def validate_events(db, date_str: str) -> list[dict]:
    """Run quality checks on a given date's data.

    Args:
        db: Database instance.
        date_str: Date string in YYYY-MM-DD format.

    Returns:
        List of issue dicts, each with 'type' and details.
    """
    issues: list[dict] = []

    # 1. Future timestamps
    issues.extend(_check_future_timestamps(db))

    # 2. Numeric range violations
    issues.extend(_check_numeric_ranges(db, date_str))

    # 3. Suspicious duplicates (>5 events from same source in same second)
    issues.extend(_check_suspicious_duplicates(db, date_str))

    # 4. Time gap detection for periodic sources
    issues.extend(_check_time_gaps(db, date_str))

    if issues:
        log.warning(f"Quality check for {date_str}: {len(issues)} issue(s) found")
    else:
        log.info(f"Quality check for {date_str}: all clear")

    return issues


def _check_future_timestamps(db) -> list[dict]:
    """Check for events with timestamps in the future."""
    issues: list[dict] = []
    try:
        cursor = db.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE timestamp_utc > datetime('now', '+1 hour')"
        )
        row = cursor.fetchone()
        count = row[0] if row else 0
        if count > 0:
            issues.append(
                {
                    "type": "future_timestamps",
                    "count": count,
                    "severity": "warning",
                    "message": f"{count} event(s) have timestamps in the future",
                }
            )
    except Exception as e:
        log.warning(f"Future timestamp check failed: {e}")
    return issues


def _check_numeric_ranges(db, date_str: str) -> list[dict]:
    """Check for values outside expected ranges."""
    issues: list[dict] = []
    for source, (min_val, max_val) in NUMERIC_RANGES.items():
        try:
            cursor = db.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE source_module = ? "
                "AND date(timestamp_local) = ? "
                "AND value_numeric IS NOT NULL "
                "AND (value_numeric < ? OR value_numeric > ?)",
                [source, date_str, min_val, max_val],
            )
            row = cursor.fetchone()
            count = row[0] if row else 0
            if count > 0:
                issues.append(
                    {
                        "type": "numeric_out_of_range",
                        "source": source,
                        "expected_range": f"{min_val}–{max_val}",
                        "count": count,
                        "severity": "warning",
                        "message": (
                            f"{count} {source} event(s) outside range "
                            f"[{min_val}, {max_val}]"
                        ),
                    }
                )
        except Exception as e:
            log.warning(f"Numeric range check failed for {source}: {e}")
    return issues


def _check_suspicious_duplicates(db, date_str: str) -> list[dict]:
    """Find instances where >5 events share the same source and second."""
    issues: list[dict] = []
    try:
        cursor = db.execute(
            "SELECT source_module, timestamp_utc, COUNT(*) as n "
            "FROM events "
            "WHERE date(timestamp_local) = ? "
            "GROUP BY source_module, timestamp_utc "
            "HAVING n > 5",
            [date_str],
        )
        rows = cursor.fetchall()
        for row in rows:
            issues.append(
                {
                    "type": "suspicious_duplicates",
                    "source": row[0],
                    "timestamp": row[1],
                    "count": row[2],
                    "severity": "warning",
                    "message": (
                        f"{row[2]} events from {row[0]} at {row[1]} "
                        f"(possible duplication)"
                    ),
                }
            )
    except Exception as e:
        log.warning(f"Duplicate check failed: {e}")
    return issues


def _check_time_gaps(db, date_str: str) -> list[dict]:
    """Find unusual gaps in periodic data sources."""
    issues: list[dict] = []
    for source, interval_min in PERIODIC_SOURCES.items():
        max_gap_min = interval_min * 3  # Allow 3x normal interval
        gaps = detect_time_gaps(db, source, date_str, max_gap_min)
        for gap in gaps:
            issues.append(
                {
                    "type": "data_gap",
                    "source": source,
                    "gap_from": gap["from"],
                    "gap_to": gap["to"],
                    "gap_minutes": gap["gap_minutes"],
                    "severity": "info",
                    "message": (
                        f"{source} gap: {gap['gap_minutes']}min "
                        f"({gap['from']} → {gap['to']})"
                    ),
                }
            )
    return issues


def detect_time_gaps(
    db, source_module: str, date_str: str, max_gap_min: int
) -> list[dict]:
    """Find gaps in periodic data that exceed max_gap_min.

    Args:
        db: Database instance.
        source_module: Source to check.
        date_str: Date to check (YYYY-MM-DD).
        max_gap_min: Maximum acceptable gap in minutes.

    Returns:
        List of gap dicts with 'from', 'to', 'gap_minutes'.
    """
    gaps: list[dict] = []
    try:
        cursor = db.execute(
            "SELECT timestamp_utc FROM events "
            "WHERE source_module = ? "
            "AND date(timestamp_local) = ? "
            "ORDER BY timestamp_utc ASC",
            [source_module, date_str],
        )
        rows = cursor.fetchall()
        if len(rows) < 2:
            return gaps

        from datetime import datetime

        timestamps = []
        for row in rows:
            ts_str = row[0]
            try:
                dt = datetime.fromisoformat(ts_str)
                timestamps.append(dt)
            except (ValueError, TypeError):
                continue

        for i in range(1, len(timestamps)):
            delta_min = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60
            if delta_min > max_gap_min:
                gaps.append(
                    {
                        "from": timestamps[i - 1].isoformat(),
                        "to": timestamps[i].isoformat(),
                        "gap_minutes": round(delta_min),
                    }
                )

    except Exception as e:
        log.warning(f"Gap detection failed for {source_module}: {e}")

    return gaps
