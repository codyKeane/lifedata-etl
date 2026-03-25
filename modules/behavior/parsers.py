"""
LifeData V4 — Behavior Module Parsers
modules/behavior/parsers.py

Parses data for passive behavioral metrics:
  app_usage_*.csv (from logs/apps/) → behavior.app_switch / transition
  unlock_*.csv   (from spool/behavior/) → behavior.unlock / latency
  steps_*.csv    (from spool/behavior/) → behavior.steps / hourly_count
  dream_*.csv    (from spool/behavior/) → behavior.dream / quick_capture
  dream_detail_*.csv (from spool/behavior/) → behavior.dream / structured_recall
"""

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.behavior.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"


def parse_app_transitions(file_path: str) -> list[Event]:
    """Parse app_usage CSV to extract app-to-app transitions with dwell times.

    CSV format (from Task 110): epoch,date,time,app_name,%APP
    Two adjacent rows give: from_app, to_app, dwell_sec.

    Filters:
      - dwell < 1 sec → screen flicker, skip
      - dwell > 3600 sec → phone was idle/locked, skip
    """
    events = []
    prev_epoch = None
    prev_app = None

    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 4:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                epoch = int(epoch_str)
                app_name = fields[3].strip()

                # Skip unresolved Tasker variables
                if app_name.startswith("%"):
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)

                if prev_epoch is not None and prev_app is not None:
                    dwell_sec = epoch - prev_epoch

                    # Filter: skip sub-second (flicker) and >1hr (idle)
                    if 1 <= dwell_sec <= 3600 and prev_app != app_name:
                        events.append(
                            Event(
                                timestamp_utc=ts_utc,
                                timestamp_local=ts_local,
                                timezone_offset=DEFAULT_TZ_OFFSET,
                                source_module="behavior.app_switch",
                                event_type="transition",
                                value_numeric=round(dwell_sec * 1000),  # dwell in ms
                                value_json=safe_json(
                                    {
                                        "from_app": prev_app,
                                        "to_app": app_name,
                                        "dwell_sec": round(dwell_sec, 1),
                                    }
                                ),
                                tags="app_switch,passive",
                                confidence=1.0,
                                parser_version=PARSER_VERSION,
                            )
                        )

                prev_epoch = epoch
                prev_app = app_name

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: app transition parse error: {e}")
                continue

    return events


def parse_unlock_latency(file_path: str) -> list[Event]:
    """Parse unlock latency CSV from Task 360.

    CSV format: epoch,time_local,timezone,latency_ms,first_app
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 5:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                latency_ms = safe_float(fields[3])
                first_app = fields[4].strip()

                if latency_ms is None:
                    continue

                # Validate range per spec: 200-30000 ms
                if latency_ms < 200 or latency_ms > 30000:
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="behavior.unlock",
                        event_type="latency",
                        value_numeric=latency_ms,
                        value_json=safe_json(
                            {
                                "latency_ms": latency_ms,
                                "first_app": first_app,
                                "unlock_method": "unknown",
                            }
                        ),
                        tags="unlock,latency,passive",
                        confidence=0.9,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: unlock latency parse error: {e}")
                continue

    return events


def parse_hourly_steps(file_path: str) -> list[Event]:
    """Parse hourly step counter CSV from Task 370.

    CSV format: epoch,time_local,timezone,hourly_steps,cumulative_counter
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 5:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                hourly_steps = safe_int(fields[3])
                cumulative = safe_int(fields[4])

                if hourly_steps is None:
                    continue

                # Sanity check: negative steps after reboot are handled by Tasker
                # but we still guard here
                if hourly_steps < 0:
                    hourly_steps = cumulative if cumulative and cumulative > 0 else 0

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="behavior.steps",
                        event_type="hourly_count",
                        value_numeric=float(hourly_steps),
                        value_json=safe_json(
                            {
                                "hourly_steps": hourly_steps,
                                "cumulative_counter": cumulative,
                                "source": "tasker_sensor",
                            }
                        ),
                        tags="steps,hourly,passive",
                        confidence=0.85,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: steps parse error: {e}")
                continue

    return events


def parse_dream_quicklog(file_path: str) -> list[Event]:
    """Parse dream quick-log CSV from Task 380.

    CSV format: epoch,time_local,timezone,vividness,tone,keywords,themes
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                # Split carefully — keywords field may contain commas
                # Format: epoch,time,tz,vividness,tone,keywords,themes
                # We split on first 6 commas
                fields = line.split(",", 6)
                if len(fields) < 7:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                vividness = safe_int(fields[3])
                tone = fields[4].strip()
                keywords = fields[5].strip()
                themes = fields[6].strip()

                if vividness is None:
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                theme_list = (
                    [t.strip() for t in themes.split(",") if t.strip()]
                    if themes
                    else []
                )

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="behavior.dream",
                        event_type="quick_capture",
                        value_numeric=float(vividness),
                        value_text=keywords,
                        value_json=safe_json(
                            {
                                "vividness": vividness,
                                "emotional_tone": tone,
                                "keywords": keywords,
                                "themes": theme_list,
                                "recall_confidence": min(vividness / 10.0, 1.0),
                            }
                        ),
                        tags="dream,quick_capture",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: dream quicklog parse error: {e}")
                continue

    return events


def parse_dream_structured(file_path: str) -> list[Event]:
    """Parse dream structured recall CSV from Task 381.

    CSV format: epoch,time_local,timezone,setting,characters,actions,emotion,connection
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                # Split on first 7 commas — fields may contain commas
                fields = line.split(",", 7)
                if len(fields) < 7:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                setting = fields[3].strip()
                characters = fields[4].strip()
                actions = fields[5].strip()
                emotion = fields[6].strip()
                connection = fields[7].strip() if len(fields) > 7 else ""

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                char_list = [c.strip() for c in characters.split(";") if c.strip()]
                setting_list = [s.strip() for s in setting.split(";") if s.strip()]
                action_list = [a.strip() for a in actions.split(";") if a.strip()]

                narrative = f"Setting: {setting}. Characters: {characters}. Events: {actions}. Emotion: {emotion}."
                if connection:
                    narrative += f" Connection: {connection}."

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="behavior.dream",
                        event_type="structured_recall",
                        value_text=narrative[:500],
                        value_json=safe_json(
                            {
                                "settings": setting_list,
                                "characters": char_list,
                                "actions": action_list,
                                "emotion": emotion,
                                "waking_connection": connection,
                            }
                        ),
                        tags="dream,structured_recall",
                        confidence=0.8,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(
                    f"{file_path}:{line_num}: dream structured parse error: {e}"
                )
                continue

    return events


# Parser registry: maps filename prefix to parser function
# Note: app_usage_ files are in logs/apps/, not spool/behavior/
SPOOL_PARSER_REGISTRY = {
    "unlock_": parse_unlock_latency,
    "steps_": parse_hourly_steps,
    "dream_detail_": parse_dream_structured,  # must come before dream_
    "dream_": parse_dream_quicklog,
}

APP_TRANSITION_PREFIX = "app_usage_"
