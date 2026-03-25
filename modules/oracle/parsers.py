"""
LifeData V4 — Oracle Module Parsers
modules/oracle/parsers.py

Parses data files for the Oracle module:
  iching_*.csv (not iching_auto_)  → oracle.iching / casting + moving_line
  iching_auto_*.csv                → oracle.iching / casting (automated)
  rng_*.csv (not rng_raw_)        → oracle.rng / hardware_sample
  rng_raw_*.csv                    → oracle.rng / raw_batch
  schumann_*.json                  → oracle.schumann / measurement
  hours_*.json                     → oracle.planetary_hours / current_hour + day_ruler
"""

from __future__ import annotations

import hashlib
import json
import math

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.oracle.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"

# ──────────────────────────────────────────────────────────────
# King Wen sequence and hexagram names (standard I Ching mapping)
# ──────────────────────────────────────────────────────────────

KING_WEN = {
    0: 2,
    1: 23,
    2: 8,
    3: 20,
    4: 16,
    5: 35,
    6: 45,
    7: 12,
    8: 15,
    9: 52,
    10: 39,
    11: 53,
    12: 62,
    13: 56,
    14: 31,
    15: 33,
    16: 7,
    17: 4,
    18: 29,
    19: 59,
    20: 40,
    21: 64,
    22: 47,
    23: 6,
    24: 46,
    25: 18,
    26: 48,
    27: 57,
    28: 32,
    29: 50,
    30: 28,
    31: 44,
    32: 24,
    33: 27,
    34: 3,
    35: 42,
    36: 51,
    37: 21,
    38: 17,
    39: 25,
    40: 36,
    41: 22,
    42: 63,
    43: 37,
    44: 55,
    45: 30,
    46: 49,
    47: 13,
    48: 19,
    49: 41,
    50: 60,
    51: 61,
    52: 54,
    53: 38,
    54: 58,
    55: 10,
    56: 11,
    57: 26,
    58: 5,
    59: 9,
    60: 34,
    61: 14,
    62: 43,
    63: 1,
}

HEX_NAMES = {
    1: "Force (Qian)",
    2: "Field (Kun)",
    3: "Sprouting (Zhun)",
    4: "Enveloping (Meng)",
    5: "Attending (Xu)",
    6: "Conflict (Song)",
    7: "Leading (Shi)",
    8: "Grouping (Bi)",
    9: "Small Accumulating",
    10: "Treading (Lu)",
    11: "Pervading (Tai)",
    12: "Obstruction (Pi)",
    13: "Concording People",
    14: "Great Possessing",
    15: "Humbling (Qian)",
    16: "Providing-For (Yu)",
    17: "Following (Sui)",
    18: "Corrupting (Gu)",
    19: "Nearing (Lin)",
    20: "Viewing (Guan)",
    21: "Gnawing Bite",
    22: "Adorning (Bi)",
    23: "Stripping (Bo)",
    24: "Returning (Fu)",
    25: "Without Embroiling",
    26: "Great Accumulating",
    27: "Swallowing (Yi)",
    28: "Great Exceeding",
    29: "Gorge (Kan)",
    30: "Radiance (Li)",
    31: "Conjoining (Xian)",
    32: "Persevering (Heng)",
    33: "Retiring (Dun)",
    34: "Great Invigorating",
    35: "Prospering (Jin)",
    36: "Brightness Hiding",
    37: "Dwelling People",
    38: "Polarising (Kui)",
    39: "Limping (Jian)",
    40: "Taking-Apart (Xie)",
    41: "Diminishing (Sun)",
    42: "Augmenting (Yi)",
    43: "Displacement (Guai)",
    44: "Coupling (Gou)",
    45: "Clustering (Cui)",
    46: "Ascending (Sheng)",
    47: "Confining (Kun)",
    48: "The Well (Jing)",
    49: "Skinning (Ge)",
    50: "The Vessel (Ding)",
    51: "Shake (Zhen)",
    52: "Bound (Gen)",
    53: "Infiltrating (Jian)",
    54: "Converting Maiden",
    55: "Abounding (Feng)",
    56: "Sojourning (Lu)",
    57: "Ground (Xun)",
    58: "Open (Dui)",
    59: "Dispersing (Huan)",
    60: "Articulating (Jie)",
    61: "Center Returning",
    62: "Small Exceeding",
    63: "Already Fording",
    64: "Not-Yet Fording",
}


# ──────────────────────────────────────────────────────────────
# I Ching Parsers
# ──────────────────────────────────────────────────────────────


def parse_iching_casting(file_path: str) -> list[Event]:
    """Parse I Ching casting CSV (interactive, from Task 350).

    CSV format:
      epoch_ts,time_local,timezone,method,hex_num,hex_name,lines,changing,result_num,result_name

    Emits one casting Event + one moving_line Event per changing line.
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 10:
                    log.warning(
                        f"iching line {line_num}: too few fields ({len(fields)})"
                    )
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                method = fields[3].strip().lower()
                hex_num = safe_int(fields[4].strip())
                hex_name = fields[5].strip()
                lines_str = fields[6].strip()
                changing_str = fields[7].strip()
                result_num = safe_int(fields[8].strip())
                result_name = fields[9].strip()

                if hex_num is None or hex_num < 1 or hex_num > 64:
                    log.warning(f"iching line {line_num}: invalid hex_num={fields[4]}")
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                # Parse line values
                line_values = [safe_int(v) for v in lines_str.split("|") if v.strip()]
                if not line_values:
                    line_values = [
                        safe_int(v) for v in lines_str.split(",") if v.strip()
                    ]

                # Parse changing lines
                changing_lines = []
                if changing_str and changing_str.lower() not in ("", "none"):
                    changing_lines = [
                        safe_int(v) for v in changing_str.split("|") if v.strip()
                    ]
                    if not changing_lines or changing_lines[0] is None:
                        changing_lines = [
                            safe_int(v) for v in changing_str.split(",") if v.strip()
                        ]
                    changing_lines = [v for v in changing_lines if v is not None]

                # Hash question if present (privacy)
                question_hash = None
                if len(fields) > 10:
                    q = fields[10].strip()
                    if q and q.lower() not in ("no_question", ""):
                        question_hash = hashlib.sha256(q.encode()).hexdigest()[:16]

                # Main casting event
                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="oracle.iching",
                        event_type="casting",
                        value_numeric=float(hex_num),
                        value_text=hex_name or HEX_NAMES.get(hex_num, "Unknown"),
                        value_json=safe_json(
                            {
                                "lines": line_values,
                                "changing_lines": changing_lines,
                                "resulting_hex": result_num,
                                "resulting_name": result_name
                                if result_name and result_name != "none"
                                else None,
                                "method": method,
                                "question_hash": question_hash,
                            }
                        ),
                        tags=f"iching,{method},casting",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

                # Moving line events
                for pos in changing_lines:
                    if pos is None or pos < 1 or pos > 6:
                        continue
                    line_val = (
                        line_values[pos - 1] if pos - 1 < len(line_values) else None
                    )
                    old_type = (
                        "yin"
                        if line_val == 6
                        else "yang"
                        if line_val == 9
                        else "unknown"
                    )
                    new_type = (
                        "yang"
                        if line_val == 6
                        else "yin"
                        if line_val == 9
                        else "unknown"
                    )

                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="oracle.iching",
                            event_type="moving_line",
                            value_numeric=float(pos),
                            value_text=f"Line {pos}: {old_type} → {new_type}",
                            value_json=safe_json(
                                {
                                    "line_position": pos,
                                    "old_value": line_val,
                                    "old_type": old_type,
                                    "new_type": new_type,
                                    "hexagram": hex_num,
                                }
                            ),
                            tags="iching,moving_line",
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"iching parse error line {line_num}: {e}")
                continue

    return events


def parse_iching_auto(file_path: str) -> list[Event]:
    """Parse automated daily I Ching casting CSV (Task 352).

    Same format as interactive but no question field. Tags as 'automated'.
    CSV format:
      epoch_ts,time_local,timezone,method,hex_num,hex_name,lines,changing,result_num,result_name
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 10:
                    log.warning(f"iching_auto line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                method = fields[3].strip().lower()
                hex_num = safe_int(fields[4].strip())
                hex_name = fields[5].strip()
                lines_str = fields[6].strip()
                changing_str = fields[7].strip()
                result_num = safe_int(fields[8].strip())
                result_name = fields[9].strip()

                if hex_num is None or hex_num < 1 or hex_num > 64:
                    log.warning(f"iching_auto line {line_num}: invalid hex_num")
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                line_values = [safe_int(v) for v in lines_str.split("|") if v.strip()]
                if not line_values:
                    line_values = [
                        safe_int(v) for v in lines_str.split(",") if v.strip()
                    ]

                changing_lines = []
                if changing_str and changing_str.lower() not in ("", "none"):
                    changing_lines = [
                        safe_int(v) for v in changing_str.split("|") if v.strip()
                    ]
                    if not changing_lines or changing_lines[0] is None:
                        changing_lines = [
                            safe_int(v) for v in changing_str.split(",") if v.strip()
                        ]
                    changing_lines = [v for v in changing_lines if v is not None]

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="oracle.iching",
                        event_type="casting",
                        value_numeric=float(hex_num),
                        value_text=hex_name or HEX_NAMES.get(hex_num, "Unknown"),
                        value_json=safe_json(
                            {
                                "lines": line_values,
                                "changing_lines": changing_lines,
                                "resulting_hex": result_num,
                                "resulting_name": result_name
                                if result_name and result_name != "none"
                                else None,
                                "method": method,
                                "automated": True,
                            }
                        ),
                        tags=f"iching,{method},casting,automated",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"iching_auto parse error line {line_num}: {e}")
                continue

    return events


# ──────────────────────────────────────────────────────────────
# RNG Parsers
# ──────────────────────────────────────────────────────────────


def parse_rng_samples(file_path: str) -> list[Event]:
    """Parse RNG sample CSV (Task 351).

    CSV format:
      epoch_ts,time_local,timezone,mean,z_score
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 5:
                    log.warning(f"rng line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                mean_val = safe_float(fields[3].strip())
                z_score = safe_float(fields[4].strip())

                if mean_val is None:
                    log.warning(f"rng line {line_num}: invalid mean")
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="oracle.rng",
                        event_type="hardware_sample",
                        value_numeric=mean_val,
                        value_json=safe_json(
                            {
                                "mean": mean_val,
                                "z_score": z_score,
                                "batch_size": 100,
                                "expected_mean": 127.5,
                            }
                        ),
                        tags="rng,hardware,sample",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"rng parse error line {line_num}: {e}")
                continue

    return events


def parse_rng_raw(file_path: str) -> list[Event]:
    """Parse raw RNG byte batch CSV.

    CSV format: single line of 100 comma-separated byte values (0-255)
    Filename encodes timestamp: rng_raw_<epoch>.csv
    """
    events: list[Event] = []
    basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    # Extract epoch from filename: rng_raw_<epoch>.csv
    parts = basename.replace(".csv", "").split("_")
    epoch_str = parts[-1] if len(parts) >= 3 else None

    if not epoch_str or not epoch_str.isdigit():
        log.warning(f"rng_raw: cannot extract epoch from {basename}")
        return events

    try:
        ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)
    except ValueError as e:
        log.warning(f"rng_raw: timestamp parse error: {e}")
        return events

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read().strip()
        if not content:
            return events

        try:
            values = [int(v.strip()) for v in content.split(",") if v.strip()]
        except ValueError:
            log.warning(f"rng_raw: invalid byte values in {basename}")
            return events

    if not values:
        return events

    n = len(values)
    mean_val = sum(values) / n
    std_val = math.sqrt(sum((x - mean_val) ** 2 for x in values) / n) if n > 1 else 0

    events.append(
        Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_local,
            timezone_offset=DEFAULT_TZ_OFFSET,
            source_module="oracle.rng",
            event_type="raw_batch",
            value_numeric=round(mean_val, 4),
            value_json=safe_json(
                {
                    "n_bytes": n,
                    "mean": round(mean_val, 4),
                    "std": round(std_val, 4),
                    "min": min(values),
                    "max": max(values),
                }
            ),
            tags="rng,raw_batch",
            confidence=1.0,
            parser_version=PARSER_VERSION,
        )
    )

    return events


# ──────────────────────────────────────────────────────────────
# Schumann Resonance Parser
# ──────────────────────────────────────────────────────────────


def parse_schumann(file_path: str) -> list[Event]:
    """Parse Schumann resonance JSON from fetch_schumann.py.

    JSON format:
    {
        "fetched_utc": "...",
        "source": "heartmath|tomsk",
        "fundamental_hz": float,
        "amplitude": float,
        "harmonics": [float, ...],
        "quality": "good|degraded"
    }
    """
    events: list[Event] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"schumann: failed to load {file_path}: {e}")
        return events

    # Handle both single measurement and array of measurements
    measurements = data if isinstance(data, list) else [data]

    for meas in measurements:
        fetched_utc = meas.get("fetched_utc")
        if not fetched_utc:
            continue

        fundamental = safe_float(meas.get("fundamental_hz"))
        if fundamental is None:
            continue

        try:
            ts_utc, ts_local = parse_timestamp(fetched_utc, DEFAULT_TZ_OFFSET)
        except ValueError:
            ts_utc = fetched_utc
            ts_local = fetched_utc

        source = meas.get("source", "unknown")
        confidence = 0.7 if source != "local" else 0.9

        events.append(
            Event(
                timestamp_utc=ts_utc,
                timestamp_local=ts_local,
                timezone_offset=DEFAULT_TZ_OFFSET,
                source_module="oracle.schumann",
                event_type="measurement",
                value_numeric=fundamental,
                value_json=safe_json(
                    {
                        "fundamental_hz": fundamental,
                        "amplitude": safe_float(meas.get("amplitude")),
                        "q_factor": safe_float(meas.get("q_factor")),
                        "harmonics": meas.get("harmonics", []),
                        "source": source,
                        "quality": meas.get("quality", "unknown"),
                    }
                ),
                tags=f"schumann,{source},measurement",
                confidence=confidence,
                parser_version=PARSER_VERSION,
            )
        )

        # Check for excursion (deviation > 0.5 Hz from baseline)
        baseline = 7.83
        if abs(fundamental - baseline) > 0.5:
            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="oracle.schumann",
                    event_type="excursion",
                    value_numeric=round(fundamental - baseline, 4),
                    value_json=safe_json(
                        {
                            "baseline_hz": baseline,
                            "actual_hz": fundamental,
                            "deviation_hz": round(fundamental - baseline, 4),
                        }
                    ),
                    tags="schumann,excursion",
                    confidence=confidence,
                    parser_version=PARSER_VERSION,
                )
            )

    return events


# ──────────────────────────────────────────────────────────────
# Planetary Hours Parser
# ──────────────────────────────────────────────────────────────


def parse_planetary_hours(file_path: str) -> list[Event]:
    """Parse planetary hours JSON from compute_planetary_hours.py.

    JSON format:
    {
        "date": "YYYY-MM-DD",
        "day_ruler": "planet_name",
        "sunrise": "ISO",
        "sunset": "ISO",
        "hours": [
            {
                "hour_number": 1-12,
                "is_night": bool,
                "ruling_planet": "planet_name",
                "start_time": "ISO",
                "end_time": "ISO",
                "duration_minutes": float
            },
            ...
        ]
    }
    """
    events: list[Event] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"planetary: failed to load {file_path}: {e}")
        return events

    date_str = data.get("date")
    day_ruler = data.get("day_ruler")
    sunrise = data.get("sunrise")
    sunset = data.get("sunset")
    hours = data.get("hours", [])

    if not date_str or not hours:
        log.warning(f"planetary: missing date or hours in {file_path}")
        return events

    # Day ruler event
    if day_ruler and sunrise:
        try:
            ts_utc, ts_local = parse_timestamp(sunrise, DEFAULT_TZ_OFFSET)
        except ValueError:
            ts_utc = f"{date_str}T06:00:00+00:00"
            ts_local = ts_utc

        events.append(
            Event(
                timestamp_utc=ts_utc,
                timestamp_local=ts_local,
                timezone_offset=DEFAULT_TZ_OFFSET,
                source_module="oracle.planetary_hours",
                event_type="day_ruler",
                value_text=day_ruler,
                value_json=safe_json(
                    {
                        "weekday": data.get("weekday"),
                        "sunrise": sunrise,
                        "sunset": sunset,
                    }
                ),
                tags=f"planetary_hours,day_ruler,{day_ruler.lower()}",
                confidence=1.0,
                parser_version=PARSER_VERSION,
            )
        )

    # Individual hour events
    for hour in hours:
        planet = hour.get("ruling_planet")
        start_time = hour.get("start_time")
        end_time = hour.get("end_time")
        hour_num = hour.get("hour_number")
        is_night = hour.get("is_night", False)

        if not planet or not start_time:
            continue

        try:
            ts_utc, ts_local = parse_timestamp(start_time, DEFAULT_TZ_OFFSET)
        except ValueError:
            continue

        events.append(
            Event(
                timestamp_utc=ts_utc,
                timestamp_local=ts_local,
                timezone_offset=DEFAULT_TZ_OFFSET,
                source_module="oracle.planetary_hours",
                event_type="current_hour",
                value_text=planet,
                value_json=safe_json(
                    {
                        "hour_number": hour_num,
                        "day_ruler": day_ruler,
                        "start_time": start_time,
                        "end_time": end_time,
                        "is_night": is_night,
                        "duration_minutes": hour.get("duration_minutes"),
                    }
                ),
                tags=f"planetary_hours,{planet.lower()},{'night' if is_night else 'day'}",
                confidence=1.0,
                parser_version=PARSER_VERSION,
            )
        )

    return events


# ──────────────────────────────────────────────────────────────
# Parser Registry
# ──────────────────────────────────────────────────────────────

# Order matters: more specific prefixes first (iching_auto_ before iching_,
# rng_raw_ before rng_)
PARSER_REGISTRY = {
    "iching_auto_": parse_iching_auto,
    "iching_": parse_iching_casting,
    "rng_raw_": parse_rng_raw,
    "rng_": parse_rng_samples,
    "schumann_": parse_schumann,
    "hours_": parse_planetary_hours,
}
