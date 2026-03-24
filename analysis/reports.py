"""
LifeData V4 — Report Generator
analysis/reports.py

Generates daily and weekly markdown reports summarizing
events, anomalies, correlations, and system health.
"""

import json
import os
from datetime import datetime, timezone

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
                f"| {row[0]} | {row[1]:.1f} | {row[2]:.1f} | {row[3]:.1f} | {row[4]} |"
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

    # ── Cognition Summary ──
    cog_bullets: list[str] = []

    rt_row = db.conn.execute(
        """
        SELECT AVG(value_numeric)
        FROM events
        WHERE source_module = 'cognition.reaction'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        """,
        [date_str],
    ).fetchone()
    if rt_row and rt_row[0] is not None:
        cog_bullets.append(f"- Avg reaction time: {rt_row[0]:.0f} ms")

    mem_row = db.conn.execute(
        """
        SELECT MAX(value_numeric)
        FROM events
        WHERE source_module = 'cognition.memory'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        """,
        [date_str],
    ).fetchone()
    if mem_row and mem_row[0] is not None:
        cog_bullets.append(f"- Working memory span: {mem_row[0]:.0f}")

    cli_row = db.conn.execute(
        """
        SELECT value_numeric
        FROM events
        WHERE source_module = 'cognition.derived'
          AND event_type = 'cognitive_load_index'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if cli_row and cli_row[0] is not None:
        cog_bullets.append(f"- Cognitive load index: {cli_row[0]:.2f}")

    imp_row = db.conn.execute(
        """
        SELECT value_numeric
        FROM events
        WHERE source_module = 'cognition.derived'
          AND event_type = 'impairment_flag'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if imp_row and imp_row[0] is not None and imp_row[0] > 0:
        cog_bullets.append("- Impairment flag: YES")

    if cog_bullets:
        sections.append("## Cognition\n")
        sections.extend(cog_bullets)
        sections.append("")

    # ── Behavior Summary ──
    beh_bullets: list[str] = []

    frag_row = db.conn.execute(
        """
        SELECT value_numeric
        FROM events
        WHERE source_module = 'behavior.app_switch.derived'
          AND event_type = 'fragmentation_index'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if frag_row and frag_row[0] is not None:
        beh_bullets.append(f"- App fragmentation: {frag_row[0]:.1f}/100")

    steps_row = db.conn.execute(
        """
        SELECT SUM(value_numeric)
        FROM events
        WHERE source_module = 'behavior.steps'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        """,
        [date_str],
    ).fetchone()
    if steps_row and steps_row[0] is not None:
        beh_bullets.append(f"- Daily steps: {steps_row[0]:,.0f}")

    att_row = db.conn.execute(
        """
        SELECT value_numeric
        FROM events
        WHERE source_module = 'behavior.derived'
          AND event_type = 'attention_span_estimate'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if att_row and att_row[0] is not None:
        beh_bullets.append(f"- Attention span: {att_row[0]:.0f}s median dwell")

    rest_row = db.conn.execute(
        """
        SELECT value_numeric
        FROM events
        WHERE source_module = 'behavior.derived'
          AND event_type = 'digital_restlessness'
          AND date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if rest_row and rest_row[0] is not None:
        rest_val = rest_row[0]
        rest_label = f"- Digital restlessness: {rest_val:.1f}\u03c3"
        if rest_val > 2.0:
            rest_label += " (elevated)"
        beh_bullets.append(rest_label)

    dream_row = db.conn.execute(
        """
        SELECT COUNT(*)
        FROM events
        WHERE source_module = 'behavior.dream'
          AND date(timestamp_local) = ?
        """,
        [date_str],
    ).fetchone()
    if dream_row and dream_row[0] > 0:
        beh_bullets.append(f"- Dreams logged: {dream_row[0]}")

    if beh_bullets:
        sections.append("## Behavior\n")
        sections.extend(beh_bullets)
        sections.append("")

    # ── Oracle Summary ──
    ora_bullets: list[str] = []

    iching_row = db.conn.execute(
        """
        SELECT COUNT(*)
        FROM events
        WHERE source_module = 'oracle.iching'
          AND date(timestamp_local) = ?
        """,
        [date_str],
    ).fetchone()
    if iching_row and iching_row[0] > 0:
        ora_bullets.append(f"- I Ching castings: {iching_row[0]}")

    rng_row = db.conn.execute(
        """
        SELECT value_json
        FROM events
        WHERE source_module = 'oracle.rng.derived'
          AND event_type = 'daily_deviation'
          AND date(timestamp_local) = ?
          AND value_json IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if rng_row and rng_row[0]:
        try:
            rng_data = json.loads(rng_row[0])
            z = rng_data.get("z")
            p = rng_data.get("p")
            if z is not None and p is not None:
                ora_bullets.append(f"- RNG deviation: z={z:.2f}, p={p:.3f}")
        except (json.JSONDecodeError, TypeError):
            pass

    schumann_row = db.conn.execute(
        """
        SELECT value_json
        FROM events
        WHERE source_module = 'oracle.schumann.derived'
          AND event_type = 'daily_summary'
          AND date(timestamp_local) = ?
          AND value_json IS NOT NULL
        ORDER BY timestamp_utc DESC LIMIT 1
        """,
        [date_str],
    ).fetchone()
    if schumann_row and schumann_row[0]:
        try:
            sch_data = json.loads(schumann_row[0])
            mean = sch_data.get("mean")
            if mean is not None:
                ora_bullets.append(f"- Schumann resonance: {mean:.2f} Hz avg")
        except (json.JSONDecodeError, TypeError):
            pass

    if ora_bullets:
        sections.append("## Oracle\n")
        sections.extend(ora_bullets)
        sections.append("")

    # ── Trends (7-day sparklines) ──
    trend_metrics = [
        ("Mood", "mind.mood", "AVG", "value_numeric"),
        ("Steps", "body.steps", "SUM", "value_numeric"),
        ("Screen time", "device.derived", "AVG", "value_numeric"),
        ("Reaction time", "cognition.reaction", "AVG", "value_numeric"),
    ]
    trend_bullets: list[str] = []

    for label, source_mod, agg_fn, _col in trend_metrics:
        # For screen time, filter to the specific event_type
        if source_mod == "device.derived":
            trend_rows = db.conn.execute(
                f"""
                SELECT date(timestamp_local) as d, {agg_fn}(value_numeric)
                FROM events
                WHERE source_module = ?
                  AND event_type = 'screen_time_minutes'
                  AND date(timestamp_local) BETWEEN date(?, '-6 days') AND ?
                  AND value_numeric IS NOT NULL
                GROUP BY d
                ORDER BY d
                """,
                [source_mod, date_str, date_str],
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

    if trend_bullets:
        sections.append("## Trends\n")
        sections.extend(trend_bullets)
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
