"""
LifeData V4 — Meta Module: Completeness Checker
modules/meta/completeness.py

Answers: "Did all expected data arrive today?"
Compares actual event counts per source_module against expected minimums
and flags missing or underperforming data streams.
"""

from core.logger import get_logger

log = get_logger("lifedata.meta.completeness")


# Required daily sources: source_module → (min_expected_events, description)
# These sources SHOULD produce data every day if the phone is on and syncing.
EXPECTED_DAILY_SOURCES = {
    "device.screen": (10, "Screen on/off events — phone was used"),
    "device.battery": (80, "Battery pulse every 15min ≈ 96/day"),
    "environment.location": (200, "Geofence every 5min ≈ 288/day"),
    "environment.hourly": (15, "Hourly snapshots 6AM–11PM ≈ 18/day"),
    "mind.evening": (1, "Evening check-in"),
}

# Optional sources: expected but variable — flag if zero.
OPTIONAL_DAILY_SOURCES = [
    "social.notification",
    "social.call",
    "social.wifi",
    "social.app_usage",
    "device.charging",
    "device.bluetooth",
    "mind.morning",
    "mind.mood",
]


def check_daily_completeness(db, date_str: str) -> dict:
    """Check data completeness for a given date.

    Args:
        db: Database instance with count_events() method.
        date_str: Date string in YYYY-MM-DD format.

    Returns:
        Dict with keys: date, required, optional, overall_pct, missing, warnings.
    """
    report = {
        "date": date_str,
        "required": {},
        "optional": {},
        "overall_pct": 0.0,
        "missing": [],
        "warnings": [],
    }

    total_expected = len(EXPECTED_DAILY_SOURCES)
    total_met = 0

    for source, (min_count, desc) in EXPECTED_DAILY_SOURCES.items():
        actual = db.count_events(source_module=source, date=date_str)
        met = actual >= min_count

        if met:
            total_met += 1
        else:
            report["missing"].append(
                {
                    "source": source,
                    "expected_min": min_count,
                    "actual": actual,
                    "description": desc,
                }
            )

        report["required"][source] = {
            "expected": min_count,
            "actual": actual,
            "met": met,
        }

    for source in OPTIONAL_DAILY_SOURCES:
        actual = db.count_events(source_module=source, date=date_str)
        report["optional"][source] = actual
        if actual == 0:
            report["warnings"].append(f"No {source} events (optional but unusual)")

    report["overall_pct"] = (
        round(total_met / total_expected * 100, 1) if total_expected > 0 else 0.0
    )

    log.info(
        f"Completeness for {date_str}: {report['overall_pct']}% "
        f"({total_met}/{total_expected} required met, "
        f"{len(report['warnings'])} optional warnings)"
    )

    return report
