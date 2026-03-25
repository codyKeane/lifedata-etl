"""
LifeData V4 — Cognition Module Parsers
modules/cognition/parsers.py

Parses CSV files for cognitive probe data from Tasker tasks:
  simple_rt_*.csv    → cognition.reaction / simple_rt + simple_rt_summary
  choice_rt_*.csv    → cognition.reaction / choice_rt
  gonogo_*.csv       → cognition.reaction / go_nogo
  digit_span_*.csv   → cognition.memory / digit_span
  time_prod_*.csv    → cognition.time / production
  time_est_*.csv     → cognition.time / estimation
  typing_*.csv       → cognition.typing / speed_test
"""

import math

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.cognition.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"


def parse_simple_rt(file_path: str) -> list[Event]:
    """Parse simple reaction time CSV.

    CSV format: epoch_ts,time_local,timezone_offset,trial_data
    trial_data: pipe-delimited color:rt_ms:wait_ms triplets

    Emits one Event per trial + one summary Event with median RT.
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 4:
                    log.warning(f"simple_rt line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                trial_data = fields[3].strip()

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                trials = [t.split(":") for t in trial_data.split("|") if t]
                rts = []

                for i, parts in enumerate(trials):
                    if len(parts) < 3:
                        continue
                    color, rt_ms_str, wait_ms_str = parts[0], parts[1], parts[2]
                    rt = safe_int(rt_ms_str)
                    wait = safe_int(wait_ms_str)
                    if rt is None:
                        continue

                    rts.append(rt)
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.reaction",
                            event_type="simple_rt",
                            value_numeric=float(rt),
                            value_json=safe_json(
                                {
                                    "color": color,
                                    "wait_ms": wait,
                                    "trial_number": i + 1,
                                    "trial_count": len(trials),
                                }
                            ),
                            tags="reaction_time,simple,probe",
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

                # Summary event: median RT
                if rts:
                    sorted_rts = sorted(rts)
                    n = len(sorted_rts)
                    median_rt = (
                        sorted_rts[n // 2]
                        if n % 2 == 1
                        else (sorted_rts[n // 2 - 1] + sorted_rts[n // 2]) / 2
                    )
                    mean_rt = sum(rts) / n
                    std_rt = (
                        math.sqrt(sum((x - mean_rt) ** 2 for x in rts) / n)
                        if n > 1
                        else 0.0
                    )

                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.reaction",
                            event_type="simple_rt_summary",
                            value_numeric=float(median_rt),
                            value_json=safe_json(
                                {
                                    "mean": round(mean_rt, 1),
                                    "std": round(std_rt, 1),
                                    "n": n,
                                    "all_rts": rts,
                                }
                            ),
                            tags="reaction_time,simple,summary",
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"simple_rt line {line_num}: {e}")
                continue

    return events


def parse_choice_rt(file_path: str) -> list[Event]:
    """Parse choice reaction time CSV.

    CSV format: epoch_ts,time_local,timezone_offset,choice,trial_data
    trial_data: pipe-delimited target:response:rt_ms:correct triplets
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
                    log.warning(f"choice_rt line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                # fields[3] = "choice" label
                trial_data = fields[4].strip()

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                trials = [t.split(":") for t in trial_data.split("|") if t]
                rts = []
                correct_count = 0

                for i, parts in enumerate(trials):
                    if len(parts) < 4:
                        continue
                    target, response, rt_ms_str, correct_str = (
                        parts[0],
                        parts[1],
                        parts[2],
                        parts[3],
                    )
                    rt = safe_int(rt_ms_str)
                    correct = safe_int(correct_str) or 0
                    if rt is None:
                        continue

                    rts.append(rt)
                    if correct:
                        correct_count += 1

                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.reaction",
                            event_type="choice_rt",
                            value_numeric=float(rt),
                            value_json=safe_json(
                                {
                                    "stimulus": target,
                                    "response": response,
                                    "correct": bool(correct),
                                    "trial_number": i + 1,
                                    "options_count": 2,
                                }
                            ),
                            tags="reaction_time,choice,probe",
                            confidence=0.95,
                            parser_version=PARSER_VERSION,
                        )
                    )

                # Summary
                if rts:
                    correct_rts = [
                        rt
                        for rt, t in zip(rts, trials)
                        if len(t) >= 4 and safe_int(t[3])
                    ]
                    summary_rts = correct_rts if correct_rts else rts
                    sorted_rts = sorted(summary_rts)
                    n = len(sorted_rts)
                    median_rt = (
                        sorted_rts[n // 2]
                        if n % 2 == 1
                        else (sorted_rts[n // 2 - 1] + sorted_rts[n // 2]) / 2
                    )

                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.reaction",
                            event_type="choice_rt_summary",
                            value_numeric=float(median_rt),
                            value_json=safe_json(
                                {
                                    "accuracy": round(
                                        correct_count / len(trials) * 100, 1
                                    )
                                    if trials
                                    else 0,
                                    "n_trials": len(trials),
                                    "n_correct": correct_count,
                                }
                            ),
                            tags="reaction_time,choice,summary",
                            confidence=0.95,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"choice_rt line {line_num}: {e}")
                continue

    return events


def parse_gonogo(file_path: str) -> list[Event]:
    """Parse Go/NoGo inhibitory control CSV.

    CSV format: epoch_ts,time_local,timezone_offset,gonogo,trial_data
    trial_data: pipe-delimited type:rt_ms:correct triplets
      type = "go" or "nogo"
      rt_ms = reaction time (or -1 if no response)
      correct = 1 or 0
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
                    log.warning(f"gonogo line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                trial_data = fields[4].strip()

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                trials = [t.split(":") for t in trial_data.split("|") if t]
                go_rts: list[int] = []
                commission_errors = 0
                omission_errors = 0
                total_go = 0
                total_nogo = 0

                for i, parts in enumerate(trials):
                    if len(parts) < 3:
                        continue
                    trial_type, rt_ms_str, correct_str = parts[0], parts[1], parts[2]
                    rt = safe_int(rt_ms_str)
                    correct = safe_int(correct_str) or 0
                    responded = rt is not None and rt > 0

                    if trial_type == "go":
                        total_go += 1
                        if responded and rt is not None:
                            go_rts.append(rt)
                        if not correct:
                            omission_errors += 1
                    elif trial_type == "nogo":
                        total_nogo += 1
                        if not correct:
                            commission_errors += 1

                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.reaction",
                            event_type="go_nogo",
                            value_numeric=float(rt) if rt is not None and responded else None,
                            value_json=safe_json(
                                {
                                    "stimulus": trial_type,
                                    "responded": responded,
                                    "correct": bool(correct),
                                    "trial_number": i + 1,
                                }
                            ),
                            tags="reaction_time,gonogo,probe",
                            confidence=0.95,
                            parser_version=PARSER_VERSION,
                        )
                    )

                # Summary
                if total_go + total_nogo > 0:
                    mean_go_rt = sum(go_rts) / len(go_rts) if go_rts else None
                    commission_rate = (
                        (commission_errors / total_nogo * 100) if total_nogo > 0 else 0
                    )
                    omission_rate = (
                        (omission_errors / total_go * 100) if total_go > 0 else 0
                    )

                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.reaction",
                            event_type="gonogo_summary",
                            value_numeric=float(mean_go_rt) if mean_go_rt else None,
                            value_json=safe_json(
                                {
                                    "commission_errors": commission_errors,
                                    "omission_errors": omission_errors,
                                    "commission_rate_pct": round(commission_rate, 1),
                                    "omission_rate_pct": round(omission_rate, 1),
                                    "total_go": total_go,
                                    "total_nogo": total_nogo,
                                    "mean_go_rt_ms": round(mean_go_rt, 1)
                                    if mean_go_rt
                                    else None,
                                }
                            ),
                            tags="reaction_time,gonogo,summary",
                            confidence=0.95,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"gonogo line {line_num}: {e}")
                continue

    return events


def parse_digit_span(file_path: str) -> list[Event]:
    """Parse digit span working memory CSV.

    CSV format: epoch_ts,time_local,timezone_offset,max_span,trial_data
    trial_data: pipe-delimited sequence:response:correct triplets
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 4:
                    log.warning(f"digit_span line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                max_span = safe_int(fields[3].strip())
                trial_data = fields[4].strip() if len(fields) > 4 else ""

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                # Parse individual trials if available
                if trial_data:
                    trials = [t.split(":") for t in trial_data.split("|") if t]
                    for i, parts in enumerate(trials):
                        if len(parts) < 3:
                            continue
                        sequence, response, correct_str = parts[0], parts[1], parts[2]
                        correct = safe_int(correct_str) or 0
                        span_len = len(sequence)

                        events.append(
                            Event(
                                timestamp_utc=ts_utc,
                                timestamp_local=ts_local,
                                timezone_offset=tz,
                                source_module="cognition.memory",
                                event_type="digit_span_trial",
                                value_numeric=float(span_len),
                                value_json=safe_json(
                                    {
                                        "sequence": sequence,
                                        "response": response,
                                        "correct": bool(correct),
                                        "trial_number": i + 1,
                                    }
                                ),
                                tags="memory,digit_span,probe",
                                confidence=1.0,
                                parser_version=PARSER_VERSION,
                            )
                        )

                # Main event: max span achieved
                if max_span is not None:
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=tz,
                            source_module="cognition.memory",
                            event_type="digit_span",
                            value_numeric=float(max_span),
                            value_json=safe_json(
                                {
                                    "max_span": max_span,
                                    "n_trials": len(trial_data.split("|"))
                                    if trial_data
                                    else 0,
                                }
                            ),
                            tags="memory,digit_span,summary",
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )

            except Exception as e:
                log.warning(f"digit_span line {line_num}: {e}")
                continue

    return events


def parse_time_production(file_path: str) -> list[Event]:
    """Parse time production CSV.

    CSV format: epoch_ts,time_local,timezone_offset,target_sec,produced_ms,error_ms,error_pct
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 7:
                    log.warning(f"time_prod line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                target_sec = safe_int(fields[3].strip())
                produced_ms = safe_int(fields[4].strip())
                error_ms = safe_int(fields[5].strip())
                error_pct = safe_float(fields[6].strip())

                if produced_ms is None:
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="cognition.time",
                        event_type="production",
                        value_numeric=float(produced_ms),
                        value_json=safe_json(
                            {
                                "target_ms": target_sec * 1000 if target_sec else None,
                                "target_sec": target_sec,
                                "error_ms": error_ms,
                                "error_pct": error_pct,
                                "direction": "under"
                                if (error_ms and error_ms < 0)
                                else "over",
                            }
                        ),
                        tags="time_perception,production,probe",
                        confidence=0.85,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"time_prod line {line_num}: {e}")
                continue

    return events


def parse_time_estimation(file_path: str) -> list[Event]:
    """Parse time estimation CSV.

    CSV format: epoch_ts,time_local,timezone_offset,actual_ms,estimate_ms,error_ms
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 6:
                    log.warning(f"time_est line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                actual_ms = safe_int(fields[3].strip())
                estimate_ms = safe_int(fields[4].strip())
                error_ms = safe_int(fields[5].strip())

                if estimate_ms is None or actual_ms is None:
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                error_pct = (
                    round((error_ms / actual_ms) * 100, 1)
                    if actual_ms and error_ms is not None
                    else None
                )

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="cognition.time",
                        event_type="estimation",
                        value_numeric=float(estimate_ms),
                        value_json=safe_json(
                            {
                                "actual_ms": actual_ms,
                                "error_ms": error_ms,
                                "error_pct": error_pct,
                                "direction": "under"
                                if (error_ms and error_ms < 0)
                                else "over",
                            }
                        ),
                        tags="time_perception,estimation,probe",
                        confidence=0.85,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"time_est line {line_num}: {e}")
                continue

    return events


def parse_typing_speed(file_path: str) -> list[Event]:
    """Parse typing speed test CSV.

    CSV format: epoch_ts,time_local,timezone_offset,wpm,accuracy_pct,errors,chars,duration_sec
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 8:
                    log.warning(f"typing line {line_num}: too few fields")
                    continue

                epoch_str = fields[0].strip()
                tz = fields[2].strip() or DEFAULT_TZ_OFFSET
                wpm = safe_int(fields[3].strip())
                accuracy = safe_float(fields[4].strip())
                errors = safe_int(fields[5].strip())
                chars = safe_int(fields[6].strip())
                duration_sec = safe_float(fields[7].strip())

                if wpm is None:
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz,
                        source_module="cognition.typing",
                        event_type="speed_test",
                        value_numeric=float(wpm),
                        value_json=safe_json(
                            {
                                "accuracy_pct": accuracy,
                                "chars": chars,
                                "errors": errors,
                                "duration_sec": duration_sec,
                            }
                        ),
                        tags="typing,speed,probe",
                        confidence=0.95,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"typing line {line_num}: {e}")
                continue

    return events


# Parser registry: filename prefix → parser function
PARSER_REGISTRY = {
    "simple_rt": parse_simple_rt,
    "choice_rt": parse_choice_rt,
    "gonogo": parse_gonogo,
    "digit_span": parse_digit_span,
    "time_prod": parse_time_production,
    "time_est": parse_time_estimation,
    "typing": parse_typing_speed,
}
