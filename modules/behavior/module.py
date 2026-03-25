"""
LifeData V4 — Behavior Module (OMICRON)
modules/behavior/module.py

Captures passive behavioral micropatterns: app switching frequency, unlock
latency, hourly step counts, and dream logs. Every metric is passively
collected from existing device interactions and sensor data.

File discovery patterns:
  logs/apps/app_usage_*.csv       → behavior.app_switch / transition
  spool/behavior/unlock_*.csv     → behavior.unlock / latency
  spool/behavior/steps_*.csv      → behavior.steps / hourly_count
  spool/behavior/dream_detail_*.csv → behavior.dream / structured_recall
  spool/behavior/dream_*.csv      → behavior.dream / quick_capture

Derived metrics (computed in post_ingest):
  behavior.app_switch / hourly_rate
  behavior.app_switch.derived / fragmentation_index
  behavior.steps / daily_total
  behavior.steps.derived / movement_entropy
  behavior.steps.derived / sedentary_bouts
  behavior.unlock / hourly_summary
  behavior.dream.derived / dream_frequency
  behavior.derived / digital_restlessness
  behavior.derived / attention_span_estimate
  behavior.derived / morning_inertia_score
  behavior.derived / behavioral_consistency
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.behavior")


class BehaviorModule(ModuleInterface):
    """Behavior module — passive behavioral exhaust metrics."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "behavior"

    @property
    def display_name(self) -> str:
        return "Behavior Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "behavior.app_switch",
            "behavior.app_switch.derived",
            "behavior.unlock",
            "behavior.unlock.derived",
            "behavior.steps",
            "behavior.steps.derived",
            "behavior.dream",
            "behavior.dream.derived",
            "behavior.derived",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all behavior-relevant files.

        Sources:
          1. logs/apps/app_usage_*.csv — reprocessed for app transitions
          2. spool/behavior/*.csv — unlock, steps, dream logs
        """
        from modules.behavior.parsers import (
            SPOOL_PARSER_REGISTRY,
            APP_TRANSITION_PREFIX,
        )

        files = []
        expanded = os.path.expanduser(raw_base)

        # 1. App usage CSVs (from social module's logs/apps/)
        apps_dir = os.path.join(expanded, "logs", "apps")
        if os.path.isdir(apps_dir):
            for csv_file in glob_files(apps_dir, "*.csv", recursive=False):
                basename = os.path.basename(csv_file)
                if basename.startswith(APP_TRANSITION_PREFIX):
                    # Skip Syncthing conflict files
                    if ".sync-conflict-" in basename:
                        continue
                    files.append(csv_file)

        # 2. Behavior spool CSVs
        spool_dir = os.path.join(expanded, "spool", "behavior")
        if os.path.isdir(spool_dir):
            for csv_file in glob_files(spool_dir, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                if any(basename.startswith(prefix) for prefix in SPOOL_PARSER_REGISTRY):
                    files.append(csv_file)

        # Deduplicate
        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single file using the appropriate parser."""
        from modules.behavior.parsers import (
            SPOOL_PARSER_REGISTRY,
            APP_TRANSITION_PREFIX,
            parse_app_transitions,
        )

        basename = os.path.basename(file_path)

        # App usage files → transition parser
        if basename.startswith(APP_TRANSITION_PREFIX):
            events = parse_app_transitions(file_path)
            if events:
                log.info(f"Parsed {len(events)} transitions from {basename}")
            return events

        # Spool files → specific parsers
        for prefix, parser_fn in SPOOL_PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for behavior file: {basename}")
        return []

    def post_ingest(self, db: Database) -> None:
        """Compute all derived behavioral metrics after ingestion.

        Derived metrics computed per day:
          - App switch hourly_rate
          - Fragmentation index (0-100)
          - Steps daily_total
          - Movement entropy
          - Sedentary bouts
          - Unlock hourly_summary
          - Dream frequency (7-day rolling)
          - Digital restlessness (composite z-score)
          - Attention span estimate (median dwell)
          - Morning inertia score
          - Behavioral consistency
        """
        derived_events = []
        baseline_days = self._config.get("baseline_window_days", 14)

        # Get all dates with behavior data
        rows = db.execute(
            """
            SELECT DISTINCT date(timestamp_utc) as d
            FROM events
            WHERE source_module LIKE 'behavior.%'
              AND source_module NOT LIKE '%.derived'
            ORDER BY d
            """
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        dates = [r[0] for r in result_set if r[0]]

        for date_str in dates:
            day_ts = f"{date_str}T23:59:00+00:00"

            # --- App switch hourly rates ---
            hourly_events = self._compute_hourly_rates(db, date_str, day_ts)
            derived_events.extend(hourly_events)

            # --- Fragmentation index ---
            frag_event = self._compute_fragmentation_index(db, date_str, day_ts)
            if frag_event:
                derived_events.append(frag_event)

            # --- Steps daily total ---
            steps_event = self._compute_daily_steps(db, date_str, day_ts)
            if steps_event:
                derived_events.append(steps_event)

            # --- Movement entropy ---
            entropy_event = self._compute_movement_entropy(db, date_str, day_ts)
            if entropy_event:
                derived_events.append(entropy_event)

            # --- Sedentary bouts ---
            sed_event = self._compute_sedentary_bouts(db, date_str, day_ts)
            if sed_event:
                derived_events.append(sed_event)

            # --- Unlock hourly summary ---
            unlock_event = self._compute_unlock_summary(db, date_str, day_ts)
            if unlock_event:
                derived_events.append(unlock_event)

            # --- Dream frequency (rolling 7d) ---
            dream_event = self._compute_dream_frequency(db, date_str, day_ts)
            if dream_event:
                derived_events.append(dream_event)

            # --- Attention span estimate ---
            attn_event = self._compute_attention_span(db, date_str, day_ts)
            if attn_event:
                derived_events.append(attn_event)

            # --- Morning inertia ---
            inertia_event = self._compute_morning_inertia(db, date_str, day_ts)
            if inertia_event:
                derived_events.append(inertia_event)

            # --- Digital restlessness (needs baseline) ---
            restless_event = self._compute_digital_restlessness(
                db, date_str, day_ts, baseline_days
            )
            if restless_event:
                derived_events.append(restless_event)

            # --- Behavioral consistency (needs baseline) ---
            consist_event = self._compute_behavioral_consistency(
                db, date_str, day_ts, baseline_days
            )
            if consist_event:
                derived_events.append(consist_event)

        # Insert all derived events
        if derived_events:
            inserted, skipped = db.insert_events_for_module("behavior", derived_events)
            log.info(
                f"Behavior derived metrics: {inserted} inserted, {skipped} skipped"
            )

    # ─── Hourly app switch rates ────────────────────────────────

    def _compute_hourly_rates(self, db: Database, date_str: str, day_ts: str) -> list[Event]:
        """Compute app switches per hour for each active hour."""
        events = []
        rows = db.execute(
            """
            SELECT CAST(strftime('%H', timestamp_utc) AS INTEGER) as hour,
                   COUNT(*) as cnt
            FROM events
            WHERE source_module = 'behavior.app_switch'
              AND event_type = 'transition'
              AND date(timestamp_utc) = ?
            GROUP BY hour
            ORDER BY hour
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows

        for row in result_set:
            hour, cnt = row[0], row[1]
            ts = f"{date_str}T{hour:02d}:59:00+00:00"
            events.append(
                Event(
                    timestamp_utc=ts,
                    timestamp_local=ts,
                    timezone_offset="-0500",
                    source_module="behavior.app_switch",
                    event_type="hourly_rate",
                    value_numeric=float(cnt),
                    value_json=safe_json({"hour": hour, "switches": cnt}),
                    tags="app_switch,hourly,derived",
                    confidence=0.8,
                    parser_version=self.version,
                )
            )

        return events

    # ─── Fragmentation index ────────────────────────────────────

    def _compute_fragmentation_index(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """0-100 scale of attention fragmentation.

        Components:
          - Switches per active hour (0-60/hr → 0-100)
          - Mean dwell time (inverse: shorter = more fragmented)
          - App diversity (Shannon entropy of to_app distribution)
        """
        ceiling = self._config.get("fragmentation_ceiling", 60)

        rows = db.execute(
            """
            SELECT value_json FROM events
            WHERE source_module = 'behavior.app_switch'
              AND event_type = 'transition'
              AND date(timestamp_utc) = ?
              AND value_json IS NOT NULL
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        if not result_set:
            return None

        dwells = []
        apps = []
        for row in result_set:
            try:
                data = json.loads(row[0])
                dwell = data.get("dwell_sec", 0)
                if 1 < dwell < 3600:
                    dwells.append(dwell)
                to_app = data.get("to_app", "")
                if to_app:
                    apps.append(to_app)
            except (json.JSONDecodeError, TypeError):
                continue

        if not dwells:
            return None

        n_switches = len(dwells)

        # Estimate active hours from first-to-last transition span
        time_rows = db.execute(
            """
            SELECT MIN(timestamp_utc), MAX(timestamp_utc) FROM events
            WHERE source_module = 'behavior.app_switch'
              AND event_type = 'transition'
              AND date(timestamp_utc) = ?
            """,
            (date_str,),
        )
        time_result = time_rows.fetchone() if hasattr(time_rows, "fetchone") else None
        if not time_result or not time_result[0] or not time_result[1]:
            return None

        t_min = datetime.fromisoformat(time_result[0])
        t_max = datetime.fromisoformat(time_result[1])
        active_hours = max((t_max - t_min).total_seconds() / 3600, 1.0)

        switch_rate = n_switches / active_hours
        mean_dwell = sum(dwells) / len(dwells)

        # App diversity (Shannon entropy)
        counts = Counter(apps)
        total = sum(counts.values())
        probs = [c / total for c in counts.values()]
        entropy = -sum(p * math.log2(p) for p in probs if p > 0)
        max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1
        norm_entropy = entropy / max_entropy if max_entropy > 0 else 0

        # Normalize to 0-100
        rate_score = min(switch_rate / ceiling * 100, 100)
        dwell_score = max(0, 100 - (mean_dwell / 120 * 100))
        entropy_score = norm_entropy * 100

        frag = round(rate_score * 0.4 + dwell_score * 0.3 + entropy_score * 0.3, 1)

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.app_switch.derived",
            event_type="fragmentation_index",
            value_numeric=frag,
            value_json=safe_json(
                {
                    "switches_per_active_hour": round(switch_rate, 1),
                    "mean_dwell_sec": round(mean_dwell, 1),
                    "app_entropy": round(entropy, 3),
                    "norm_entropy": round(norm_entropy, 3),
                    "active_hours": round(active_hours, 2),
                    "n_switches": n_switches,
                }
            ),
            tags="fragmentation,attention,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Daily steps total ──────────────────────────────────────

    def _compute_daily_steps(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Sum hourly step counts into a daily total."""
        rows = db.execute(
            """
            SELECT SUM(value_numeric) as total, COUNT(*) as hours
            FROM events
            WHERE source_module = 'behavior.steps'
              AND event_type = 'hourly_count'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (date_str,),
        )
        result = rows.fetchone() if hasattr(rows, "fetchone") else None
        if not result or result[0] is None or result[0] == 0:
            return None

        total_steps = int(result[0])
        step_goal = self._config.get("step_goal", 8000)
        goal_pct = round(total_steps / step_goal * 100, 1) if step_goal > 0 else 0

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.steps",
            event_type="daily_total",
            value_numeric=float(total_steps),
            value_json=safe_json(
                {
                    "total_steps": total_steps,
                    "hours_recorded": result[1],
                    "goal_pct": goal_pct,
                    "step_goal": step_goal,
                }
            ),
            tags="steps,daily,derived",
            confidence=0.85,
            parser_version=self.version,
        )

    # ─── Movement entropy ───────────────────────────────────────

    def _compute_movement_entropy(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Shannon entropy of hourly step distribution (0-1 normalized).

        High = steps spread evenly (active lifestyle).
        Low = steps concentrated in 1-2 hours (sedentary with bursts).
        """
        rows = db.execute(
            """
            SELECT CAST(strftime('%H', timestamp_utc) AS INTEGER) as hour,
                   SUM(value_numeric) as steps
            FROM events
            WHERE source_module = 'behavior.steps'
              AND event_type = 'hourly_count'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            GROUP BY hour
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        if not result_set:
            return None

        # Build 24-hour array
        hourly = [0] * 24
        for row in result_set:
            h, s = row[0], row[1]
            if 0 <= h < 24 and s:
                hourly[h] = int(s)

        total = sum(hourly)
        if total == 0:
            return None

        nonzero = [s for s in hourly if s > 0]
        if len(nonzero) < 2:
            return None

        probs = [s / total for s in nonzero]
        entropy = -sum(p * math.log2(p) for p in probs)
        max_entropy = math.log2(len(nonzero))
        norm = round(entropy / max_entropy, 3) if max_entropy > 0 else 0.0

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.steps.derived",
            event_type="movement_entropy",
            value_numeric=norm,
            value_json=safe_json(
                {
                    "raw_entropy_bits": round(entropy, 3),
                    "active_hours": len(nonzero),
                    "total_steps": total,
                    "hourly_distribution": hourly,
                }
            ),
            tags="steps,entropy,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Sedentary bouts ────────────────────────────────────────

    def _compute_sedentary_bouts(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Find consecutive waking hours with <threshold steps."""
        threshold = self._config.get("sedentary_threshold", 50)
        min_bout = self._config.get("sedentary_min_bout_hours", 2)

        rows = db.execute(
            """
            SELECT CAST(strftime('%H', timestamp_utc) AS INTEGER) as hour,
                   SUM(value_numeric) as steps
            FROM events
            WHERE source_module = 'behavior.steps'
              AND event_type = 'hourly_count'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            GROUP BY hour
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        if not result_set:
            return None

        hourly = [0] * 24
        for row in result_set:
            h, s = row[0], row[1]
            if 0 <= h < 24 and s:
                hourly[h] = int(s)

        # Detect bouts during waking hours (6-23)
        bouts: list[dict[str, Any]] = []
        bout_start: int | None = None
        bout_len = 0

        for h in range(6, 24):
            if hourly[h] < threshold:
                if bout_start is None:
                    bout_start = h
                bout_len += 1
            else:
                if bout_len >= min_bout:
                    bouts.append(
                        {
                            "start_hour": bout_start,
                            "end_hour": h,
                            "duration_hours": bout_len,
                            "total_steps": sum(hourly[bout_start:h]),
                        }
                    )
                bout_start = None
                bout_len = 0

        # Handle bout extending to end of day
        if bout_len >= min_bout:
            bouts.append(
                {
                    "start_hour": bout_start,
                    "end_hour": 23,
                    "duration_hours": bout_len,
                    "total_steps": sum(hourly[bout_start:24]),
                }
            )

        if not bouts:
            return None

        longest = max(bouts, key=lambda b: b["duration_hours"])

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.steps.derived",
            event_type="sedentary_bouts",
            value_numeric=float(len(bouts)),
            value_json=safe_json(
                {
                    "bouts": bouts,
                    "longest_bout_hours": longest["duration_hours"],
                    "threshold_steps": threshold,
                }
            ),
            tags="steps,sedentary,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Unlock hourly summary ──────────────────────────────────

    def _compute_unlock_summary(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Summary stats for unlock latency over the day."""
        rows = db.execute(
            """
            SELECT value_numeric FROM events
            WHERE source_module = 'behavior.unlock'
              AND event_type = 'latency'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        latencies = [r[0] for r in result_set if r[0] is not None]

        if not latencies:
            return None

        n = len(latencies)
        mean_lat = sum(latencies) / n
        std_lat = (
            math.sqrt(sum((x - mean_lat) ** 2 for x in latencies) / n) if n > 1 else 0
        )

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.unlock",
            event_type="hourly_summary",
            value_numeric=round(mean_lat, 1),
            value_json=safe_json(
                {
                    "n_unlocks": n,
                    "mean_latency_ms": round(mean_lat, 1),
                    "std_ms": round(std_lat, 1),
                    "fastest_ms": round(min(latencies), 1),
                    "slowest_ms": round(max(latencies), 1),
                }
            ),
            tags="unlock,summary,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Dream frequency ────────────────────────────────────────

    def _compute_dream_frequency(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Rolling 7-day dream log count."""
        rows = db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE source_module = 'behavior.dream'
              AND event_type IN ('quick_capture', 'structured_recall')
              AND date(timestamp_utc) BETWEEN date(?, '-6 days') AND ?
            """,
            (date_str, date_str),
        )
        result = rows.fetchone() if hasattr(rows, "fetchone") else None
        if not result or result[0] == 0:
            return None

        count = result[0]

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.dream.derived",
            event_type="dream_frequency",
            value_numeric=float(count),
            value_json=safe_json(
                {
                    "dreams_7d": count,
                    "dreams_per_week": count,
                    "window_end": date_str,
                }
            ),
            tags="dream,frequency,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Attention span estimate ────────────────────────────────

    def _compute_attention_span(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Median app dwell time, excluding calls/media/launcher."""
        rows = db.execute(
            """
            SELECT value_json FROM events
            WHERE source_module = 'behavior.app_switch'
              AND event_type = 'transition'
              AND date(timestamp_utc) = ?
              AND value_json IS NOT NULL
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        if not result_set:
            return None

        excluded = {
            "dialer",
            "incallui",
            "music",
            "spotify",
            "youtube.music",
            "launcher",
            "systemui",
            "notification shade",
        }
        dwells = []
        for row in result_set:
            try:
                data = json.loads(row[0])
                to_app = data.get("to_app", "").lower()
                if any(ex in to_app for ex in excluded):
                    continue
                dwell = data.get("dwell_sec", 0)
                if 1 < dwell < 3600:
                    dwells.append(dwell)
            except (json.JSONDecodeError, TypeError):
                continue

        if len(dwells) < 5:
            return None

        dwells.sort()
        n = len(dwells)
        median = (
            dwells[n // 2] if n % 2 == 1 else (dwells[n // 2 - 1] + dwells[n // 2]) / 2
        )

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.derived",
            event_type="attention_span_estimate",
            value_numeric=round(median, 1),
            value_json=safe_json(
                {
                    "median_dwell_sec": round(median, 1),
                    "n_transitions": n,
                    "p25_dwell_sec": round(dwells[n // 4], 1),
                    "p75_dwell_sec": round(dwells[3 * n // 4], 1),
                }
            ),
            tags="attention,dwell,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Morning inertia ────────────────────────────────────────

    def _compute_morning_inertia(self, db: Database, date_str: str, day_ts: str) -> Optional[Event]:
        """Minutes from first screen_on to first productive app usage.

        Uses the same productive_keywords as the social module's
        digital_hygiene computation for consistency.
        """
        productive_keywords = {
            "terminal",
            "code",
            "editor",
            "file",
            "calendar",
            "email",
            "mail",
            "clock",
            "calculator",
            "notes",
            "settings",
            "dialer",
            "contacts",
            "maps",
            "camera",
            "syncthing",
            "tasker",
        }

        # Get first screen_on of the day
        screen_rows = db.execute(
            """
            SELECT timestamp_utc FROM events
            WHERE source_module = 'device.screen'
              AND event_type = 'screen_on'
              AND date(timestamp_utc) = ?
            ORDER BY timestamp_utc ASC
            LIMIT 1
            """,
            (date_str,),
        )
        screen_result = (
            screen_rows.fetchone() if hasattr(screen_rows, "fetchone") else None
        )
        if not screen_result or not screen_result[0]:
            return None

        first_on = datetime.fromisoformat(screen_result[0])

        # Get app transitions after first screen on
        app_rows = db.execute(
            """
            SELECT timestamp_utc, value_json FROM events
            WHERE source_module = 'behavior.app_switch'
              AND event_type = 'transition'
              AND date(timestamp_utc) = ?
              AND timestamp_utc >= ?
            ORDER BY timestamp_utc ASC
            """,
            (date_str, screen_result[0]),
        )
        app_set = app_rows.fetchall() if hasattr(app_rows, "fetchall") else app_rows

        for row in app_set:
            try:
                data = json.loads(row[1])
                to_app = data.get("to_app", "").lower()
                if any(kw in to_app for kw in productive_keywords):
                    app_time = datetime.fromisoformat(row[0])
                    delta_min = (app_time - first_on).total_seconds() / 60
                    if delta_min > 360:
                        break  # > 6 hours is not morning inertia
                    return Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="behavior.derived",
                        event_type="morning_inertia_score",
                        value_numeric=round(delta_min, 1),
                        value_json=safe_json(
                            {
                                "first_screen_on": screen_result[0],
                                "first_productive_app": data.get("to_app", ""),
                                "minutes": round(delta_min, 1),
                            }
                        ),
                        tags="morning,inertia,derived",
                        confidence=0.8,
                        parser_version=self.version,
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        return None

    # ─── Digital restlessness ───────────────────────────────────

    def _compute_digital_restlessness(
        self, db: Database, date_str: str, day_ts: str, baseline_days: int
    ) -> Optional[Event]:
        """Composite z-score: app switches + unlock frequency + screen time.

        Weights: frag × 0.4, unlocks × 0.3, screen_time × 0.3.
        Requires at least 7 days of baseline data.
        """
        # Today's values
        frag_val = self._get_today_metric(
            db, date_str, "behavior.app_switch.derived", "fragmentation_index"
        )
        unlock_rows = db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE source_module = 'behavior.unlock'
              AND event_type = 'latency'
              AND date(timestamp_utc) = ?
            """,
            (date_str,),
        )
        unlock_result = unlock_rows.fetchone()
        unlock_count = unlock_result[0] if unlock_result else 0

        screen_rows = db.execute(
            """
            SELECT value_numeric FROM events
            WHERE source_module = 'device.derived'
              AND event_type = 'screen_time_minutes'
              AND date(timestamp_utc) = ?
            """,
            (date_str,),
        )
        screen_result = (
            screen_rows.fetchone() if hasattr(screen_rows, "fetchone") else None
        )
        screen_min = screen_result[0] if screen_result and screen_result[0] else None

        components = {}

        # Z-score each component against baseline
        if frag_val is not None:
            z = self._zscore_against_baseline(
                db,
                date_str,
                baseline_days,
                frag_val,
                "behavior.app_switch.derived",
                "fragmentation_index",
            )
            if z is not None:
                components["frag"] = z

        if unlock_count > 0:
            z = self._zscore_unlock_count(db, date_str, baseline_days, unlock_count)
            if z is not None:
                components["unlocks"] = z

        if screen_min is not None:
            z = self._zscore_against_baseline(
                db,
                date_str,
                baseline_days,
                screen_min,
                "device.derived",
                "screen_time_minutes",
            )
            if z is not None:
                components["screen"] = z

        if len(components) < 2:
            return None

        weights = {"frag": 0.4, "unlocks": 0.3, "screen": 0.3}
        total_weight = sum(weights.get(k, 0.3) for k in components)
        restlessness = (
            sum(components[k] * weights.get(k, 0.3) for k in components) / total_weight
        )

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.derived",
            event_type="digital_restlessness",
            value_numeric=round(restlessness, 3),
            value_json=safe_json(
                {
                    "components": {k: round(v, 3) for k, v in components.items()},
                    "weights": {k: weights.get(k, 0.3) for k in components},
                    "n_components": len(components),
                }
            ),
            tags="restlessness,composite,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Behavioral consistency ─────────────────────────────────

    def _compute_behavioral_consistency(
        self, db: Database, date_str: str, day_ts: str, baseline_days: int
    ) -> Optional[Event]:
        """Std of today's hourly activity pattern vs 14-day profile.

        Low score = routine is consistent = healthy.
        High score = erratic schedule.
        """
        # Today's hourly app switch profile
        today_rows = db.execute(
            """
            SELECT CAST(strftime('%H', timestamp_utc) AS INTEGER) as hour,
                   COUNT(*) as cnt
            FROM events
            WHERE source_module = 'behavior.app_switch'
              AND event_type = 'transition'
              AND date(timestamp_utc) = ?
            GROUP BY hour
            """,
            (date_str,),
        )
        today_set = (
            today_rows.fetchall() if hasattr(today_rows, "fetchall") else today_rows
        )
        if not today_set:
            return None

        today_profile = [0.0] * 24
        for row in today_set:
            h = row[0]
            if 0 <= h < 24:
                today_profile[h] = float(row[1])

        # Baseline: average hourly profile over past N days
        bl_rows = db.execute(
            """
            SELECT sub.hour, AVG(sub.cnt) as avg_cnt
            FROM (
                SELECT date(timestamp_utc) as d,
                       CAST(strftime('%H', timestamp_utc) AS INTEGER) as hour,
                       COUNT(*) as cnt
                FROM events
                WHERE source_module = 'behavior.app_switch'
                  AND event_type = 'transition'
                  AND date(timestamp_utc) BETWEEN date(?, ? || ' days') AND date(?, '-1 day')
                GROUP BY d, hour
            ) sub
            GROUP BY sub.hour
            """,
            (date_str, str(-baseline_days), date_str),
        )
        bl_set: list[Any] = bl_rows.fetchall() if hasattr(bl_rows, "fetchall") else list(bl_rows)
        if not bl_set or len(bl_set) < 3:
            return None

        baseline_profile = [0.0] * 24
        for row in bl_set:
            h = row[0]
            if 0 <= h < 24 and row[1] is not None:
                baseline_profile[h] = float(row[1])

        # Compute deviation: RMSE of today vs baseline (waking hours only)
        diffs = []
        for h in range(6, 24):
            if baseline_profile[h] > 0 or today_profile[h] > 0:
                diffs.append((today_profile[h] - baseline_profile[h]) ** 2)

        if len(diffs) < 3:
            return None

        rmse = math.sqrt(sum(diffs) / len(diffs))

        return Event(
            timestamp_utc=day_ts,
            timestamp_local=day_ts,
            timezone_offset="-0500",
            source_module="behavior.derived",
            event_type="behavioral_consistency",
            value_numeric=round(rmse, 2),
            value_json=safe_json(
                {
                    "rmse": round(rmse, 2),
                    "today_active_hours": sum(
                        1 for h in range(6, 24) if today_profile[h] > 0
                    ),
                    "baseline_days": baseline_days,
                }
            ),
            tags="consistency,routine,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    # ─── Helper methods ─────────────────────────────────────────

    def _get_today_metric(self, db: Database, date_str: str, source_module: str, event_type: str) -> Optional[float]:
        """Get today's value for a specific derived metric."""
        rows = db.execute(
            """
            SELECT value_numeric FROM events
            WHERE source_module = ? AND event_type = ?
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            LIMIT 1
            """,
            (source_module, event_type, date_str),
        )
        result = rows.fetchone() if hasattr(rows, "fetchone") else None
        return result[0] if result else None

    def _zscore_against_baseline(
        self,
        db: Database,
        date_str: str,
        baseline_days: int,
        today_val: float,
        source_module: str,
        event_type: str,
    ) -> Optional[float]:
        """Z-score today's value against a rolling baseline."""
        rows = db.execute(
            """
            SELECT value_numeric FROM events
            WHERE source_module = ? AND event_type = ?
              AND date(timestamp_utc) BETWEEN date(?, ? || ' days') AND date(?, '-1 day')
              AND value_numeric IS NOT NULL
            """,
            (source_module, event_type, date_str, str(-baseline_days), date_str),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        vals = [r[0] for r in result_set if r[0] is not None]

        if len(vals) < 7:
            return None

        mean_val = sum(vals) / len(vals)
        std_val = math.sqrt(sum((x - mean_val) ** 2 for x in vals) / len(vals))
        if std_val < 0.01:
            return None

        return float((today_val - mean_val) / std_val)

    def _zscore_unlock_count(
        self, db: Database, date_str: str, baseline_days: int, today_count: int
    ) -> Optional[float]:
        """Z-score today's unlock count against baseline daily counts."""
        rows = db.execute(
            """
            SELECT date(timestamp_utc) as d, COUNT(*) as cnt
            FROM events
            WHERE source_module = 'behavior.unlock'
              AND event_type = 'latency'
              AND date(timestamp_utc) BETWEEN date(?, ? || ' days') AND date(?, '-1 day')
            GROUP BY d
            """,
            (date_str, str(-baseline_days), date_str),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        counts = [r[1] for r in result_set if r[1] is not None]

        if len(counts) < 7:
            return None

        mean_c = sum(counts) / len(counts)
        std_c = math.sqrt(sum((x - mean_c) ** 2 for x in counts) / len(counts))
        if std_c < 0.01:
            return None

        return float((today_count - mean_c) / std_c)

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily behavior metrics for report generation."""
        rows = db.execute(
            """
            SELECT source_module, event_type, COUNT(*) as cnt,
                   AVG(value_numeric) as avg_val,
                   MIN(value_numeric) as min_val,
                   MAX(value_numeric) as max_val
            FROM events
            WHERE source_module LIKE 'behavior.%'
              AND date(timestamp_utc) = ?
            GROUP BY source_module, event_type
            """,
            (date_str,),
        )

        summary = {}
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        for row in result_set:
            src, evt, cnt, avg_val, min_val, max_val = row
            key = f"{src}.{evt}"
            summary[key] = {
                "count": cnt,
                "avg": round(avg_val, 2) if avg_val is not None else None,
                "min": round(min_val, 2) if min_val is not None else None,
                "max": round(max_val, 2) if max_val is not None else None,
            }

        if not summary:
            return None

        return {
            "event_counts": summary,
            "total_behavior_events": sum(v["count"] for v in summary.values()),
        }


def create_module(config: dict[str, Any] | None = None) -> BehaviorModule:
    """Factory function called by the orchestrator."""
    return BehaviorModule(config)
