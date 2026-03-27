"""
LifeData V4 — Report Generator
analysis/reports.py

Generates daily and weekly markdown reports summarizing
events, anomalies, correlations, and system health.
"""

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from analysis.anomaly import AnomalyDetector
from analysis.registry import MetricsRegistry
from core.logger import get_logger
from core.utils import today_local

log = get_logger("lifedata.analysis.reports")


def _read_version() -> str:
    """Read version from pyproject.toml — single source of truth."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    for line in pyproject.read_text().splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "4.0.0"


_REPORT_VERSION = _read_version()

# Allowlist of safe SQL aggregate functions — prevents injection via config
_AGG_SQL = {"AVG": "AVG", "SUM": "SUM", "MIN": "MIN", "MAX": "MAX", "COUNT": "COUNT"}


def _yaml_frontmatter(
    report_type: str,
    date_str: str,
    event_count: int,
    anomaly_count: int,
) -> str:
    """Build a YAML frontmatter block for a report.

    Returns a string starting and ending with '---' lines.
    """
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    lines = [
        "---",
        f"type: {report_type}",
        f"date: {date_str}",
        f"generated: {generated}",
        f"event_count: {event_count}",
        f"anomaly_count: {anomaly_count}",
        f"version: {_REPORT_VERSION}",
        "---",
    ]
    return "\n".join(lines)


def _resolve_trend_metrics(
    configured_trends: list[str],
    modules: list | None = None,
) -> list[tuple[str, str, str, str | None]]:
    """Resolve trend metric config into (label, source_module, agg_fn, event_type) tuples.

    If configured_trends is provided (from config.yaml), parse those.
    Otherwise fall back to metrics flagged trend_eligible in module manifests.
    """
    if configured_trends:
        trend_metrics = []
        for name in configured_trends:
            if ":" in name:
                src, evt = name.split(":", 1)
                label = evt.replace("_", " ").title()
                trend_metrics.append((label, src, "AVG", evt))
            else:
                label = name.split(".")[-1].replace("_", " ").title()
                trend_metrics.append((label, name, "AVG", None))
        return trend_metrics

    # Registry-based fallback: use trend_eligible metrics from module manifests
    if modules:
        registry = MetricsRegistry(modules=modules)
        trend_metrics = []
        for m in registry.get_trend_metrics():
            name = m["name"]
            label = m.get("display_name", name.split(".")[-1].replace("_", " ").title())
            agg = m.get("aggregate", "AVG")
            evt = m.get("event_type")
            src = name.split(":")[0] if ":" in name else name
            trend_metrics.append((label, src, agg, evt))
        return trend_metrics

    return []


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

    trend_metrics = _resolve_trend_metrics(configured_trends, modules)

    trend_bullets: list[str] = []

    for label, source_mod, agg_fn, event_type_filter in trend_metrics:
        safe_agg = _AGG_SQL.get(agg_fn.upper(), "AVG") if agg_fn else "AVG"
        if event_type_filter:
            trend_rows = db.conn.execute(
                f"""
                SELECT date(timestamp_local) as d, {safe_agg}(value_numeric)
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
                SELECT date(timestamp_local) as d, {safe_agg}(value_numeric)
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

    # Count anomalies for frontmatter
    anomaly_count = len(anomalies) + len(patterns)

    frontmatter = _yaml_frontmatter(
        report_type="daily",
        date_str=date_str,
        event_count=total,
        anomaly_count=anomaly_count,
    )
    report_content = frontmatter + "\n" + "\n".join(sections)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    log.info(f"Daily report written to {report_path}")
    return report_path


def _generate_period_report(
    db,
    modules: list = None,
    config: dict = None,
    end_date: str | None = None,
    period_days: int = 7,
    period_label: str = "Weekly",
    subdir: str = "weekly",
) -> str:
    """Generate a weekly or monthly aggregated report in markdown.

    Aggregates daily data over the period rather than recomputing from scratch.

    Args:
        db: Database instance.
        modules: List of module instances.
        config: Full config dict.
        end_date: Last day of the period (default: today local).
        period_days: Number of days to cover (7 for weekly, 30 for monthly).
        period_label: Human label ("Weekly" or "Monthly").
        subdir: Subdirectory under reports_dir ("weekly" or "monthly").

    Returns:
        Path to the generated report file.
    """
    tz_name = "America/Chicago"
    if config:
        tz_name = config.get("lifedata", {}).get("timezone", tz_name)

    end_date = end_date or today_local(tz_name)
    sections: list[str] = []

    # Compute start date using SQLite date math for consistency
    start_date_row = db.conn.execute(
        "SELECT date(?, ?)",
        [end_date, f"-{period_days - 1} days"],
    ).fetchone()
    start_date = start_date_row[0]

    # ── Header ──
    sections.append(
        f"# LifeData {period_label} Report — {start_date} to {end_date}\n"
    )
    sections.append(
        f"*Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}*\n"
    )

    # ── Summary Statistics (trend metrics over the period) ──
    analysis_cfg = (config or {}).get("lifedata", {}).get("analysis", {})
    report_cfg = analysis_cfg.get("report", {})
    configured_trends = report_cfg.get("trend_metrics", [])

    trend_metrics = _resolve_trend_metrics(configured_trends, modules)

    stat_rows_data: list[tuple[str, float, float, float, str]] = []

    for label, source_mod, agg_fn, event_type_filter in trend_metrics:
        safe_agg = _AGG_SQL.get(agg_fn.upper(), "AVG") if agg_fn else "AVG"
        if event_type_filter:
            daily_rows = db.conn.execute(
                f"""
                SELECT date(timestamp_local) as d, {safe_agg}(value_numeric)
                FROM events
                WHERE source_module = ?
                  AND event_type = ?
                  AND date(timestamp_local) BETWEEN ? AND ?
                  AND value_numeric IS NOT NULL
                GROUP BY d
                ORDER BY d
                """,
                [source_mod, event_type_filter, start_date, end_date],
            ).fetchall()
        else:
            daily_rows = db.conn.execute(
                f"""
                SELECT date(timestamp_local) as d, {safe_agg}(value_numeric)
                FROM events
                WHERE source_module = ?
                  AND date(timestamp_local) BETWEEN ? AND ?
                  AND value_numeric IS NOT NULL
                GROUP BY d
                ORDER BY d
                """,
                [source_mod, start_date, end_date],
            ).fetchall()

        if daily_rows:
            vals = [r[1] for r in daily_rows]
            avg_val = sum(vals) / len(vals)
            min_val = min(vals)
            max_val = max(vals)
            spark = _sparkline(vals) if len(vals) >= 2 else ""
            stat_rows_data.append((label, avg_val, min_val, max_val, spark))

    if stat_rows_data:
        sections.append("## Summary Statistics\n")
        sections.append("| Metric | Avg | Min | Max | Trend |")
        sections.append("|--------|-----|-----|-----|-------|")
        for label, avg_val, min_val, max_val, spark in stat_rows_data:
            sections.append(
                f"| {label} | {avg_val:.1f} | {min_val:.1f} | {max_val:.1f} | {spark} |"
            )
        sections.append("")

    # ── Module Summaries (event counts per module over the period) ──
    sections.append("## Module Summaries\n")

    rows = db.conn.execute(
        """
        SELECT source_module, COUNT(*) as n
        FROM events
        WHERE date(timestamp_local) BETWEEN ? AND ?
        GROUP BY source_module
        ORDER BY n DESC
        """,
        [start_date, end_date],
    ).fetchall()

    total = sum(r[1] for r in rows)
    sections.append(f"**Total events: {total:,}**\n")
    sections.append("| Source | Count |")
    sections.append("|--------|-------|")
    for row in rows:
        sections.append(f"| {row[0]} | {row[1]:,} |")
    sections.append("")

    # ── Anomaly Summary (count anomalies over the period) ──
    detector = AnomalyDetector(db, config=config)
    total_anomalies = 0

    # Generate date range in Python — works for arbitrary period lengths
    period_start = date.fromisoformat(start_date)
    period_end = date.fromisoformat(end_date)
    period_dates = []
    cursor_date = period_start
    while cursor_date <= period_end:
        period_dates.append(cursor_date.isoformat())
        cursor_date += timedelta(days=1)

    for day_str in period_dates:
        try:
            day_anomalies = detector.check_today(day_str)
            total_anomalies += len(day_anomalies)
        except Exception:
            pass

    sections.append("## Anomaly Summary\n")
    sections.append(f"**Total anomalies detected: {total_anomalies}**\n")

    # ── Hypothesis Results ──
    hypotheses_cfg = analysis_cfg.get("hypotheses", [])
    if hypotheses_cfg:
        sections.append("## Hypothesis Results\n")
        sections.append("| Hypothesis | Direction | Status |")
        sections.append("|------------|-----------|--------|")
        for h in hypotheses_cfg:
            if not h.get("enabled", True):
                continue
            name = h.get("name", "?")
            direction = h.get("direction", "any")
            # Query correlation data for the two metrics over the period
            metric_a = h.get("metric_a", "")
            metric_b = h.get("metric_b", "")
            corr_row = db.conn.execute(
                """
                SELECT pearson_r FROM correlations
                WHERE metric_a = ? AND metric_b = ?
                ORDER BY computed_utc DESC LIMIT 1
                """,
                [metric_a, metric_b],
            ).fetchone()
            if corr_row and corr_row[0] is not None:
                r = corr_row[0]
                if direction == "positive":
                    status = "Supported" if r > 0 else "Not supported"
                elif direction == "negative":
                    status = "Supported" if r < 0 else "Not supported"
                else:
                    status = f"r={r:.3f}"
            else:
                status = "Insufficient data"
            sections.append(f"| {name} | {direction} | {status} |")
        sections.append("")

    # ── Write Report ──
    reports_dir = "~/LifeData/reports/" + subdir
    if config:
        reports_dir = config.get("lifedata", {}).get(
            "reports_dir", "~/LifeData/reports"
        )
        reports_dir = os.path.join(reports_dir, subdir)

    expanded_dir = os.path.expanduser(reports_dir)
    os.makedirs(expanded_dir, exist_ok=True)

    report_path = os.path.join(expanded_dir, f"report_{end_date}.md")

    frontmatter = _yaml_frontmatter(
        report_type=period_label.lower(),
        date_str=end_date,
        event_count=total,
        anomaly_count=total_anomalies,
    )
    report_content = frontmatter + "\n" + "\n".join(sections)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    log.info(f"{period_label} report written to {report_path}")
    return report_path


def generate_weekly_report(
    db,
    modules: list = None,
    config: dict = None,
    end_date: str | None = None,
) -> str:
    """Generate a weekly report covering the last 7 days.

    Args:
        db: Database instance.
        modules: List of module instances.
        config: Full config dict.
        end_date: Last day of the period (default: today local).

    Returns:
        Path to the generated report file.
    """
    return _generate_period_report(
        db,
        modules=modules,
        config=config,
        end_date=end_date,
        period_days=7,
        period_label="Weekly",
        subdir="weekly",
    )


def generate_monthly_report(
    db,
    modules: list = None,
    config: dict = None,
    end_date: str | None = None,
) -> str:
    """Generate a monthly report covering the last 30 days.

    Args:
        db: Database instance.
        modules: List of module instances.
        config: Full config dict.
        end_date: Last day of the period (default: today local).

    Returns:
        Path to the generated report file.
    """
    return _generate_period_report(
        db,
        modules=modules,
        config=config,
        end_date=end_date,
        period_days=30,
        period_label="Monthly",
        subdir="monthly",
    )
