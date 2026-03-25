"""
LifeData V4 — Mind Module Parsers
modules/mind/parsers.py

Parses Tasker-generated CSV files for subjective check-in events:
  - morning_*.csv → mind.morning, mind.mood, mind.energy, mind.sleep
  - evening_*.csv → mind.evening, mind.mood, mind.stress

Handles both standard (auto-triggered) and manual entry variants.
Manual entries are identified by a "manual" source tag in the last field.

CSV Formats (refactored Tasker tasks):
  Morning (standard): epoch,date,time,sleep_quality,dream_recall,mood,energy
  Morning (manual):   epoch,date,time,sleep_quality,dream_recall,mood,energy,manual
  Evening (standard): epoch,date,time,day_rating,stress,productivity,social
  Evening (manual):   epoch,date,time,day_rating,stress,productivity,social,manual
"""


from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_json

log = get_logger("lifedata.mind.parsers")

# Default timezone offset when CSVs don't include %TIMEZONE
DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"

# Morning check field indices (after epoch,date,time)
MORNING_FIELDS = ["sleep_quality", "dream_recall", "mood", "energy"]

# Evening check field indices (after epoch,date,time)
EVENING_FIELDS = ["day_rating", "stress", "productivity", "social_satisfaction"]


def _parse_csv_line(line: str) -> list[str] | None:
    """Split a CSV line into fields, returning None for blank/malformed lines."""
    line = line.strip()
    if not line:
        return None
    return line.split(",")


def _detect_manual(fields: list[str], expected_data_count: int) -> tuple[bool, str]:
    """Detect if a row is from a manual entry and extract timezone info.

    Manual entries have an extra 'manual' tag appended.
    Returns (is_manual, tz_offset).
    """
    # Count data fields (everything after epoch,date,time)
    data_fields = fields[3:]

    # Check if last field is "manual" tag
    is_manual = False
    if data_fields and data_fields[-1].strip().lower() == "manual":
        is_manual = True

    return is_manual, DEFAULT_TZ_OFFSET


def parse_morning(file_path: str) -> list[Event]:
    """Parse morning check-in CSV.

    Emits:
      - mind.morning / assessment  (composite JSON of all scores)
      - mind.sleep  / check_in     (sleep_quality as value_numeric)
      - mind.mood   / check_in     (mood score as value_numeric)
      - mind.energy / check_in     (energy score as value_numeric)
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            fields = _parse_csv_line(line)
            if not fields:
                continue

            try:
                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    log.debug(f"{file_path}:{line_num}: skipping non-epoch line")
                    continue

                if len(fields) < 7:
                    log.warning(
                        f"{file_path}:{line_num}: too few fields "
                        f"({len(fields)}, need ≥7)"
                    )
                    continue

                is_manual, tz_offset = _detect_manual(fields, len(MORNING_FIELDS))

                ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

                # Extract scores
                sleep_quality = safe_float(fields[3])
                dream_recall = safe_float(fields[4])
                mood = safe_float(fields[5])
                energy = safe_float(fields[6])

                source_tag = "manual" if is_manual else "auto"
                tags = f"check_in,morning,{source_tag}"

                # --- Composite assessment event ---
                assessment = {
                    "sleep_quality": sleep_quality,
                    "dream_recall": dream_recall,
                    "mood": mood,
                    "energy": energy,
                    "source": source_tag,
                }
                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_offset,
                        source_module="mind.morning",
                        event_type="assessment",
                        value_json=safe_json(assessment),
                        tags=tags,
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

                # --- Individual score events ---
                if sleep_quality is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.sleep",
                            event_type="check_in",
                            value_numeric=sleep_quality,
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

                if mood is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.mood",
                            event_type="check_in",
                            value_numeric=mood,
                            value_text="morning",
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

                if energy is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.energy",
                            event_type="check_in",
                            value_numeric=energy,
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: parse error: {e}")
                continue

    return events


def parse_evening(file_path: str) -> list[Event]:
    """Parse evening check-in CSV.

    Emits:
      - mind.evening / assessment  (composite JSON of all scores)
      - mind.mood    / check_in    (day_rating as value_numeric, text="evening")
      - mind.stress  / check_in    (stress level as value_numeric)
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            fields = _parse_csv_line(line)
            if not fields:
                continue

            try:
                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    log.debug(f"{file_path}:{line_num}: skipping non-epoch line")
                    continue

                if len(fields) < 7:
                    log.warning(
                        f"{file_path}:{line_num}: too few fields "
                        f"({len(fields)}, need ≥7)"
                    )
                    continue

                is_manual, tz_offset = _detect_manual(fields, len(EVENING_FIELDS))

                ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

                # Extract scores
                day_rating = safe_float(fields[3])
                stress = safe_float(fields[4])
                productivity = safe_float(fields[5])
                social_satisfaction = safe_float(fields[6])

                source_tag = "manual" if is_manual else "auto"
                tags = f"check_in,evening,{source_tag}"

                # --- Composite assessment event ---
                assessment = {
                    "day_rating": day_rating,
                    "stress": stress,
                    "productivity": productivity,
                    "social_satisfaction": social_satisfaction,
                    "source": source_tag,
                }
                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_offset,
                        source_module="mind.evening",
                        event_type="assessment",
                        value_json=safe_json(assessment),
                        tags=tags,
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

                # --- Individual score events ---
                if day_rating is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.mood",
                            event_type="check_in",
                            value_numeric=day_rating,
                            value_text="evening",
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

                if stress is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.stress",
                            event_type="check_in",
                            value_numeric=stress,
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

                if productivity is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.productivity",
                            event_type="check_in",
                            value_numeric=productivity,
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

                if social_satisfaction is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz_offset,
                            source_module="mind.social_satisfaction",
                            event_type="check_in",
                            value_numeric=social_satisfaction,
                            tags=tags,
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: parse error: {e}")
                continue

    return events


# Parser registry: maps filename prefix to parser function
PARSER_REGISTRY = {
    "morning_": parse_morning,
    "evening_": parse_evening,
}
