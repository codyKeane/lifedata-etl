"""
LifeData V4 — Report Generator
analysis/reports.py

Generates daily and weekly markdown reports summarizing
events, anomalies, correlations, and system health.
"""

import os
from datetime import UTC, datetime

from analysis.anomaly import AnomalyDetector
from core.logger import get_logger
from core.utils import today_local

log = get_logger("lifedata.analysis.reports")


def _sparkline(values: list[float]) -> str:
    """Convert a list of values to a text sparkline using Unicode blocks."""
    if not values or len(values) < 2:
        return ""
    blocks = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    lo, hi = min(values), max(values)
    if hi == lo:
        return blocks[4] * len(values)
    scale = (len(blocks) - 1) / (hi - lo)
    return "".join(blocks[int((v - lo) * scale)] for v in values)


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
        f"*Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}*\n"
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
                f"| {row[0]} | {row[1]:.1f} | {row[2]:.1f} | {row[3]:.1f} | {row[4]} |"
            )
        sections.append("")

    # ── Module Summaries (sovereignty-preserving: each module renders its own section) ──
    # Determine section order from config, or use default module order
    analysis_cfg_sections = (config or {}).get("lifedata", {}).get("analysis", {})
    report_cfg_sections = analysis_cfg_sections.get("report", {}).get("sections", [])

    if modules and report_cfg_sections:
        # Config-driven section order — only show enabled sections
        ordered_modules = [
            m for s in report_cfg_sections if s.get("enabled", True)
            for m in (modules or []) if m.module_id == s["module"]
        ]
    elif modules:
        ordered_modules = list(modules)
    else:
        ordered_modules = []

    for mod in ordered_modules:
        try:
            summary = mod.get_daily_summary(db, date_str)
        except Exception as e:
            log.warning(f"get_daily_summary() failed for {mod.module_id}: {e}")
            continue

        if summary is None:
            continue

        mod_bullets = summary.get("bullets", [])
        if not mod_bullets:
            continue

        title = summary.get("section_title", mod.display_name)
        sections.append(f"## {title}\n")
        sections.extend(mod_bullets)
        sections.append("")

    # ── Trends (7-day sparklines) ──
    # Load trend metrics from config if available, else use hardcoded defaults
    analysis_cfg = (config or {}).get("lifedata", {}).get("analysis", {})
    report_cfg = analysis_cfg.get("report", {})
    configured_trends = report_cfg.get("trend_metrics", [])

    if configured_trends:
        # Config-driven trends: parse "source_module:event_type" format
        trend_metrics = []
        for name in configured_trends:
            if ":" in name:
                src, evt = name.split(":", 1)
                # Use the event_type as the display label
                label = evt.replace("_", " ").title()
                trend_metrics.append((label, src, "AVG", evt))
            else:
                label = name.split(".")[-1].replace("_", " ").title()
                trend_metrics.append((label, name, "AVG", None))
    else:
        # Legacy hardcoded defaults
        trend_metrics = [
            ("Mood", "mind.mood", "AVG", None),
            ("Steps", "body.steps", "SUM", None),
            ("Screen time", "device.derived", "AVG", "screen_time_minutes"),
            ("Reaction time", "cognition.reaction", "AVG", None),
        ]

    trend_bullets: list[str] = []

    for label, source_mod, agg_fn, event_type_filter in trend_metrics:
        if event_type_filter:
            trend_rows = db.conn.execute(
                f"""
                SELECT date(timestamp_local) as d, {agg_fn}(value_numeric)
                FROM events
                WHERE source_module = ?
                  AND event_type = ?
                  AND date(timestamp_local) BETWEEN date(?, '-6 days') AND ?
                  AND value_numeric IS NOT NULL
                GROUP BY d
                ORDER BY d
                """,
                [source_mod, event_type_filter, date_str, date_str],
            ).fetchall()
        else:
            trend_rows = db.conn.execute(
                f"""
                SELECT date(timestamp_local) as d, {agg_fn}(value_numeric)
                FROM events
                WHERE source_module = ?
                  AND date(timestamp_local) BETWEEN date(?, '-6 days') AND ?
                  AND value_numeric IS NOT NULL
                GROUP BY d
                ORDER BY d
                """,
                [source_mod, date_str, date_str],
            ).fetchall()

        if trend_rows and len(trend_rows) >= 2:
            vals = [r[1] for r in trend_rows]
            spark = _sparkline(vals)
            lo, hi = min(vals), max(vals)
            trend_bullets.append(
                f"- {label} (7d): {spark} (range: {lo:.0f}\u2013{hi:.0f})"
            )
        elif not trend_rows:
            log.warning(f"Trend metric '{source_mod}' returned no data for {date_str}")

    if trend_bullets:
        sections.append("## Trends\n")
        sections.extend(trend_bullets)
        sections.append("")

    # ── Anomalies ──
    detector = AnomalyDetector(db, config=config)
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
