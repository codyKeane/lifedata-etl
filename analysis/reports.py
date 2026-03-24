"""
LifeData V4 — Report Generator
analysis/reports.py

Generates daily and weekly markdown reports summarizing
events, anomalies, correlations, and system health.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from analysis.anomaly import AnomalyDetector
from core.logger import get_logger
from core.utils import today_local

log = get_logger("lifedata.analysis.reports")


def generate_daily_report(
    db,
    modules: list = None,
    config: dict = None,
    date_str: str | None = None,
) -> str:
    """Generate a comprehensive daily report in markdown.

    Args:
        db: Database instance.
        modules: List of module instances (for display names).
        config: Full config dict.
        date_str: Date to report on (default: today local).

    Returns:
        Path to the generated report file.
    """
    tz_name = "America/Chicago"
    if config:
        tz_name = config.get("lifedata", {}).get("timezone", tz_name)

    date_str = date_str or today_local(tz_name)
    sections: list[str] = []

    # ── Header ──
    sections.append(f"# LifeData Daily Report — {date_str}\n")
    sections.append(
        f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n"
    )

    # ── Data Summary ──
    sections.append("## Data Summary\n")

    # Count events by source module for this date
    rows = db.conn.execute(
        """
        SELECT source_module, COUNT(*) as n
        FROM events
        WHERE date(timestamp_local) = ?
        GROUP BY source_module
        ORDER BY n DESC
        """,
        [date_str],
    ).fetchall()

    total = sum(r[1] for r in rows)
    sections.append(f"**Total events: {total:,}**\n")
    sections.append("| Source | Count |")
    sections.append("|--------|-------|")
    for row in rows:
        sections.append(f"| {row[0]} | {row[1]:,} |")
    sections.append("")

    # ── Numeric Metrics ──
    metric_rows = db.conn.execute(
        """
        SELECT source_module,
               AVG(value_numeric) as avg_val,
               MIN(value_numeric) as min_val,
               MAX(value_numeric) as max_val,
               COUNT(*) as n
        FROM events
        WHERE date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        GROUP BY source_module
        ORDER BY source_module
        """,
        [date_str],
    ).fetchall()

    if metric_rows:
        sections.append("## Metrics\n")
        sections.append("| Metric | Avg | Min | Max | N |")
        sections.append("|--------|-----|-----|-----|---|")
        for row in metric_rows:
            sections.append(
                f"| {row[0]} | {row[1]:.1f} | {row[2]:.1f} | "
                f"{row[3]:.1f} | {row[4]} |"
            )
        sections.append("")

    # ── Device Summary ──
    battery_rows = db.conn.execute(
        """
        SELECT MIN(value_numeric) as min_batt, MAX(value_numeric) as max_batt,
               AVG(value_numeric) as avg_batt
        FROM events
        WHERE source_module = 'device.battery'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        """,
        [date_str],
    ).fetchone()

    if battery_rows and battery_rows[0] is not None:
        sections.append("## Device\n")
        sections.append(
            f"- Battery range: {battery_rows[0]:.0f}% – {battery_rows[1]:.0f}% "
            f"(avg {battery_rows[2]:.0f}%)"
        )

        screen_count = db.conn.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE source_module = 'device.screen'
              AND date(timestamp_local) = ?
            """,
            [date_str],
        ).fetchone()[0]
        sections.append(f"- Screen events: {screen_count}")

        charge_count = db.conn.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE source_module = 'device.charging'
              AND date(timestamp_local) = ?
            """,
            [date_str],
        ).fetchone()[0]
        sections.append(f"- Charging events: {charge_count}")
        sections.append("")

    # ── Environment Summary ──
    hourly_row = db.conn.execute(
        """
        SELECT AVG(value_numeric), MIN(value_numeric), MAX(value_numeric)
        FROM events
        WHERE source_module = 'environment.hourly'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        """,
        [date_str],
    ).fetchone()

    if hourly_row and hourly_row[0] is not None:
        sections.append("## Environment\n")
        sections.append(
            f"- Temperature: {hourly_row[1]:.0f}°F – {hourly_row[2]:.0f}°F "
            f"(avg {hourly_row[0]:.0f}°F)"
        )

        loc_count = db.conn.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE source_module = 'environment.location'
              AND date(timestamp_local) = ?
            """,
            [date_str],
        ).fetchone()[0]
        sections.append(f"- Location fixes: {loc_count}")
        sections.append("")

    # ── Social Summary ──
    social_rows = db.conn.execute(
        """
        SELECT source_module, COUNT(*) as n
        FROM events
        WHERE source_module LIKE 'social.%'
          AND date(timestamp_local) = ?
        GROUP BY source_module
        ORDER BY n DESC
        """,
        [date_str],
    ).fetchall()

    if social_rows:
        sections.append("## Social & Apps\n")
        for row in social_rows:
            label = row[0].replace("social.", "").replace("_", " ").title()
            sections.append(f"- {label}: {row[1]:,}")
        sections.append("")

    # ── Anomalies ──
    detector = AnomalyDetector(db)
    anomalies = detector.check_today(date_str)
    if anomalies:
        sections.append("## Anomalies Detected\n")
        for a in anomalies:
            icon = "🔴" if a["severity"] == "extreme" else "🟡"
            sections.append(f"- {icon} {a['human_readable']}")
        sections.append("")

    # ── Pattern Alerts ──
    patterns = detector.check_pattern_anomalies(date_str)
    if patterns:
        sections.append("## Pattern Alerts\n")
        for p in patterns:
            sections.append(f"- ⚠️ **{p['pattern']}**: {p['description']}")
        sections.append("")

    # ── Module Status ──
    mod_rows = db.conn.execute(
        "SELECT module_id, last_status, last_run_utc FROM modules ORDER BY module_id"
    ).fetchall()

    if mod_rows:
        sections.append("## Module Status\n")
        sections.append("| Module | Status | Last Run |")
        sections.append("|--------|--------|----------|")
        for row in mod_rows:
            status_icon = "✅" if row[1] == "success" else "❌"
            last_run = row[2][:19] if row[2] else "—"
            sections.append(f"| {row[0]} | {status_icon} {row[1]} | {last_run} |")
        sections.append("")

    # ── Write Report ──
    reports_dir = "~/LifeData/reports/daily"
    if config:
        reports_dir = config.get("lifedata", {}).get(
            "reports_dir", "~/LifeData/reports"
        )
        reports_dir = os.path.join(reports_dir, "daily")

    expanded_dir = os.path.expanduser(reports_dir)
    os.makedirs(expanded_dir, exist_ok=True)

    report_path = os.path.join(expanded_dir, f"report_{date_str}.md")
    report_content = "\n".join(sections)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    log.info(f"Daily report written to {report_path}")
    return report_path
