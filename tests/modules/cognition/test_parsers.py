"""
Tests for modules/cognition/parsers.py — simple_rt, choice_rt, gonogo,
digit_span, time_production, time_estimation, typing_speed.
"""

import json

from modules.cognition.parsers import (
    parse_choice_rt,
    parse_digit_span,
    parse_gonogo,
    parse_simple_rt,
    parse_time_estimation,
    parse_time_production,
    parse_typing_speed,
)

# ──────────────────────────────────────────────────────────────
# Simple RT parser
# ──────────────────────────────────────────────────────────────


class TestParseSimpleRt:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,red:320:1500|green:280:2000|blue:310:1800",
        ]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        events = parse_simple_rt(path)
        # 3 trials + 1 summary = 4 events
        assert len(events) == 4
        trials = [e for e in events if e.event_type == "simple_rt"]
        summary = [e for e in events if e.event_type == "simple_rt_summary"]
        assert len(trials) == 3
        assert len(summary) == 1
        assert trials[0].value_numeric == 320.0
        assert trials[0].source_module == "cognition.reaction"

    def test_summary_median(self, csv_file_factory):
        """Median of [280, 310, 320] = 310."""
        lines = [
            "1711303200,10:00:00,-0500,red:320:1500|green:280:2000|blue:310:1800",
        ]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        events = parse_simple_rt(path)
        summary = [e for e in events if e.event_type == "simple_rt_summary"][0]
        assert summary.value_numeric == 310.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0700,red:320:1500"]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        events = parse_simple_rt(path)
        assert events[0].timezone_offset == "-0700"

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00"]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        events = parse_simple_rt(path)
        assert len(events) == 0

    def test_bad_trial_data_skipped(self, csv_file_factory):
        """Trial with fewer than 3 parts should be skipped."""
        lines = ["1711303200,10:00:00,-0500,red:320"]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        events = parse_simple_rt(path)
        # 0 trials parsed → no events
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("simple_rt_2026.csv", [])
        assert parse_simple_rt(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,red:320:1500|green:280:2000"]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        for e in parse_simple_rt(path):
            assert e.is_valid

    def test_deterministic(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,red:320:1500|green:280:2000"]
        path = csv_file_factory("simple_rt_2026.csv", lines)
        ids1 = [e.event_id for e in parse_simple_rt(path)]
        ids2 = [e.event_id for e in parse_simple_rt(path)]
        assert ids1 == ids2


# ──────────────────────────────────────────────────────────────
# Choice RT parser
# ──────────────────────────────────────────────────────────────


class TestParseChoiceRt:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,choice,left:left:350:1|right:left:420:0|left:left:290:1",
        ]
        path = csv_file_factory("choice_rt_2026.csv", lines)
        events = parse_choice_rt(path)
        trials = [e for e in events if e.event_type == "choice_rt"]
        summary = [e for e in events if e.event_type == "choice_rt_summary"]
        assert len(trials) == 3
        assert len(summary) == 1

    def test_accuracy_in_summary(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,choice,left:left:350:1|right:left:420:0",
        ]
        path = csv_file_factory("choice_rt_2026.csv", lines)
        events = parse_choice_rt(path)
        summary = [e for e in events if e.event_type == "choice_rt_summary"][0]
        data = json.loads(summary.value_json)
        assert data["accuracy"] == 50.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,+0100,choice,left:left:350:1",
        ]
        path = csv_file_factory("choice_rt_2026.csv", lines)
        events = parse_choice_rt(path)
        assert events[0].timezone_offset == "+0100"

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500"]
        path = csv_file_factory("choice_rt_2026.csv", lines)
        assert parse_choice_rt(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("choice_rt_2026.csv", [])
        assert parse_choice_rt(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,choice,left:left:350:1"]
        path = csv_file_factory("choice_rt_2026.csv", lines)
        for e in parse_choice_rt(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Go/NoGo parser
# ──────────────────────────────────────────────────────────────


class TestParseGoNogo:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,gonogo,go:320:1|nogo:-1:1|go:280:1|nogo:250:0",
        ]
        path = csv_file_factory("gonogo_2026.csv", lines)
        events = parse_gonogo(path)
        trials = [e for e in events if e.event_type == "go_nogo"]
        summary = [e for e in events if e.event_type == "gonogo_summary"]
        assert len(trials) == 4
        assert len(summary) == 1

    def test_commission_error_rate(self, csv_file_factory):
        """nogo trial with response = commission error."""
        lines = [
            "1711303200,10:00:00,-0500,gonogo,go:320:1|nogo:250:0",
        ]
        path = csv_file_factory("gonogo_2026.csv", lines)
        events = parse_gonogo(path)
        summary = [e for e in events if e.event_type == "gonogo_summary"][0]
        data = json.loads(summary.value_json)
        assert data["commission_errors"] == 1
        assert data["commission_rate_pct"] == 100.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0600,gonogo,go:320:1"]
        path = csv_file_factory("gonogo_2026.csv", lines)
        events = parse_gonogo(path)
        assert events[0].timezone_offset == "-0600"

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("gonogo_2026.csv", [])
        assert parse_gonogo(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,gonogo,go:320:1|nogo:-1:1"]
        path = csv_file_factory("gonogo_2026.csv", lines)
        for e in parse_gonogo(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Digit span parser
# ──────────────────────────────────────────────────────────────


class TestParseDigitSpan:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,7,12345:12345:1|123456:123465:0|1234567:1234567:1",
        ]
        path = csv_file_factory("digit_span_2026.csv", lines)
        events = parse_digit_span(path)
        trials = [e for e in events if e.event_type == "digit_span_trial"]
        main = [e for e in events if e.event_type == "digit_span"]
        assert len(trials) == 3
        assert len(main) == 1
        assert main[0].value_numeric == 7.0

    def test_no_trial_data(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5"]
        path = csv_file_factory("digit_span_2026.csv", lines)
        events = parse_digit_span(path)
        # Should still produce main event even without trial data
        assert len(events) == 1
        assert events[0].event_type == "digit_span"
        assert events[0].value_numeric == 5.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,+0900,5"]
        path = csv_file_factory("digit_span_2026.csv", lines)
        events = parse_digit_span(path)
        assert events[0].timezone_offset == "+0900"

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00"]
        path = csv_file_factory("digit_span_2026.csv", lines)
        assert parse_digit_span(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("digit_span_2026.csv", [])
        assert parse_digit_span(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,7,12345:12345:1"]
        path = csv_file_factory("digit_span_2026.csv", lines)
        for e in parse_digit_span(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Time production parser
# ──────────────────────────────────────────────────────────────


class TestParseTimeProduction:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,5,5250,250,5.0",
        ]
        path = csv_file_factory("time_prod_2026.csv", lines)
        events = parse_time_production(path)
        assert len(events) == 1
        assert events[0].source_module == "cognition.time"
        assert events[0].event_type == "production"
        assert events[0].value_numeric == 5250.0

    def test_error_direction(self, csv_file_factory):
        """Negative error_ms → 'under' direction."""
        lines = ["1711303200,10:00:00,-0500,5,4800,-200,-4.0"]
        path = csv_file_factory("time_prod_2026.csv", lines)
        events = parse_time_production(path)
        data = json.loads(events[0].value_json)
        assert data["direction"] == "under"

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,+0530,5,5250,250,5.0"]
        path = csv_file_factory("time_prod_2026.csv", lines)
        events = parse_time_production(path)
        assert events[0].timezone_offset == "+0530"

    def test_missing_produced_ms(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5,NaN,NaN,NaN"]
        path = csv_file_factory("time_prod_2026.csv", lines)
        events = parse_time_production(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5,5250"]
        path = csv_file_factory("time_prod_2026.csv", lines)
        assert parse_time_production(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("time_prod_2026.csv", [])
        assert parse_time_production(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5,5250,250,5.0"]
        path = csv_file_factory("time_prod_2026.csv", lines)
        for e in parse_time_production(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Time estimation parser
# ──────────────────────────────────────────────────────────────


class TestParseTimeEstimation:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,5000,5300,300",
        ]
        path = csv_file_factory("time_est_2026.csv", lines)
        events = parse_time_estimation(path)
        assert len(events) == 1
        assert events[0].source_module == "cognition.time"
        assert events[0].event_type == "estimation"
        assert events[0].value_numeric == 5300.0

    def test_error_pct_computed(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5000,5300,300"]
        path = csv_file_factory("time_est_2026.csv", lines)
        events = parse_time_estimation(path)
        data = json.loads(events[0].value_json)
        assert data["error_pct"] == 6.0  # 300/5000 * 100

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0800,5000,5300,300"]
        path = csv_file_factory("time_est_2026.csv", lines)
        events = parse_time_estimation(path)
        assert events[0].timezone_offset == "-0800"

    def test_missing_estimate(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5000,NaN,NaN"]
        path = csv_file_factory("time_est_2026.csv", lines)
        events = parse_time_estimation(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,5000"]
        path = csv_file_factory("time_est_2026.csv", lines)
        assert parse_time_estimation(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("time_est_2026.csv", [])
        assert parse_time_estimation(path) == []


# ──────────────────────────────────────────────────────────────
# Typing speed parser
# ──────────────────────────────────────────────────────────────


class TestParseTypingSpeed:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,65,97.5,3,120,30.0",
        ]
        path = csv_file_factory("typing_2026.csv", lines)
        events = parse_typing_speed(path)
        assert len(events) == 1
        assert events[0].source_module == "cognition.typing"
        assert events[0].event_type == "speed_test"
        assert events[0].value_numeric == 65.0

    def test_json_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,65,97.5,3,120,30.0"]
        path = csv_file_factory("typing_2026.csv", lines)
        events = parse_typing_speed(path)
        data = json.loads(events[0].value_json)
        assert data["accuracy_pct"] == 97.5
        assert data["errors"] == 3
        assert data["chars"] == 120
        assert data["duration_sec"] == 30.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,+0200,65,97.5,3,120,30.0"]
        path = csv_file_factory("typing_2026.csv", lines)
        events = parse_typing_speed(path)
        assert events[0].timezone_offset == "+0200"

    def test_non_numeric_wpm_skipped(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,fast,97.5,3,120,30.0"]
        path = csv_file_factory("typing_2026.csv", lines)
        events = parse_typing_speed(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,65"]
        path = csv_file_factory("typing_2026.csv", lines)
        assert parse_typing_speed(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("typing_2026.csv", [])
        assert parse_typing_speed(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,65,97.5,3,120,30.0"]
        path = csv_file_factory("typing_2026.csv", lines)
        for e in parse_typing_speed(path):
            assert e.is_valid
