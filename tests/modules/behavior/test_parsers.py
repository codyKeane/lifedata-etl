"""
Tests for modules/behavior/parsers.py — app_transitions, unlock_latency,
hourly_steps, dream_quicklog, dream_structured.
"""

import json

from modules.behavior.parsers import (
    parse_app_transitions,
    parse_dream_quicklog,
    parse_dream_structured,
    parse_hourly_steps,
    parse_unlock_latency,
)

# ──────────────────────────────────────────────────────────────
# App transitions parser
# ──────────────────────────────────────────────────────────────


class TestParseAppTransitions:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,3-24-26,10:00,com.slack.android,%APP",
            "1711303260,3-24-26,10:01,com.google.chrome,%APP",
            "1711303500,3-24-26,10:05,com.twitter.android,%APP",
        ]
        path = csv_file_factory("app_usage_2026.csv", lines)
        events = parse_app_transitions(path)
        # 3 rows → 2 transitions
        assert len(events) == 2
        assert events[0].source_module == "behavior.app_switch"
        assert events[0].event_type == "transition"
        data = json.loads(events[0].value_json)
        assert data["from_app"] == "com.slack.android"
        assert data["to_app"] == "com.google.chrome"
        assert data["dwell_sec"] == 60.0

    def test_sub_second_dwell_filtered(self, csv_file_factory):
        """Dwell < 1 sec is screen flicker — skip."""
        lines = [
            "1711303200,3-24-26,10:00,com.slack.android,%APP",
            "1711303200,3-24-26,10:00,com.google.chrome,%APP",  # same second
        ]
        path = csv_file_factory("app_usage_2026.csv", lines)
        events = parse_app_transitions(path)
        assert len(events) == 0

    def test_long_dwell_filtered(self, csv_file_factory):
        """Dwell > 3600 sec (1 hour) is idle — skip."""
        lines = [
            "1711303200,3-24-26,10:00,com.slack.android,%APP",
            "1711310401,3-24-26,12:01,com.google.chrome,%APP",  # 7201 sec
        ]
        path = csv_file_factory("app_usage_2026.csv", lines)
        events = parse_app_transitions(path)
        assert len(events) == 0

    def test_same_app_not_transition(self, csv_file_factory):
        """Same app → same app is not a transition."""
        lines = [
            "1711303200,3-24-26,10:00,com.slack.android,%APP",
            "1711303260,3-24-26,10:01,com.slack.android,%APP",
        ]
        path = csv_file_factory("app_usage_2026.csv", lines)
        events = parse_app_transitions(path)
        assert len(events) == 0

    def test_tasker_variable_skipped(self, csv_file_factory):
        """Unresolved %APP variable should be skipped."""
        lines = [
            "1711303200,3-24-26,10:00,%APP_NAME,%APP",
        ]
        path = csv_file_factory("app_usage_2026.csv", lines)
        events = parse_app_transitions(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00"]
        path = csv_file_factory("app_usage_2026.csv", lines)
        assert parse_app_transitions(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("app_usage_2026.csv", [])
        assert parse_app_transitions(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = [
            "1711303200,3-24-26,10:00,com.slack.android,%APP",
            "1711303260,3-24-26,10:01,com.google.chrome,%APP",
        ]
        path = csv_file_factory("app_usage_2026.csv", lines)
        for e in parse_app_transitions(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Unlock latency parser
# ──────────────────────────────────────────────────────────────


class TestParseUnlockLatency:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,850,com.android.launcher",
            "1711306800,11:00:00,-0500,1200,com.slack.android",
        ]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        assert len(events) == 2
        assert events[0].source_module == "behavior.unlock"
        assert events[0].event_type == "latency"
        assert events[0].value_numeric == 850.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        """Per-row timezone must be used, not DEFAULT_TZ_OFFSET."""
        lines = ["1711303200,10:00:00,-0700,850,com.android.launcher"]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        assert events[0].timezone_offset == "-0700"

    def test_below_200ms_skipped(self, csv_file_factory):
        """Latency < 200ms is out of spec range."""
        lines = ["1711303200,10:00:00,-0500,100,com.android.launcher"]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        assert len(events) == 0

    def test_above_30000ms_skipped(self, csv_file_factory):
        """Latency > 30000ms is out of spec range."""
        lines = ["1711303200,10:00:00,-0500,31000,com.android.launcher"]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        assert len(events) == 0

    def test_boundary_200ms(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,200,com.android.launcher"]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        assert len(events) == 1

    def test_first_app_in_json(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,850,com.slack.android"]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        data = json.loads(events[0].value_json)
        assert data["first_app"] == "com.slack.android"

    def test_non_numeric_latency_skipped(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,NaN,com.android.launcher"]
        path = csv_file_factory("unlock_2026.csv", lines)
        events = parse_unlock_latency(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500"]
        path = csv_file_factory("unlock_2026.csv", lines)
        assert parse_unlock_latency(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("unlock_2026.csv", [])
        assert parse_unlock_latency(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,850,com.android.launcher"]
        path = csv_file_factory("unlock_2026.csv", lines)
        for e in parse_unlock_latency(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Hourly steps parser
# ──────────────────────────────────────────────────────────────


class TestParseHourlySteps:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,1500,12500",
            "1711306800,11:00:00,-0500,800,13300",
        ]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_hourly_steps(path)
        assert len(events) == 2
        assert events[0].source_module == "behavior.steps"
        assert events[0].event_type == "hourly_count"
        assert events[0].value_numeric == 1500.0

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,+0530,1500,12500"]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_hourly_steps(path)
        assert events[0].timezone_offset == "+0530"

    def test_negative_steps_fallback(self, csv_file_factory):
        """Negative hourly steps (reboot) should fall back to cumulative."""
        lines = ["1711303200,10:00:00,-0500,-100,500"]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_hourly_steps(path)
        assert len(events) == 1
        assert events[0].value_numeric == 500.0  # fallback to cumulative

    def test_cumulative_in_json(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,1500,12500"]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_hourly_steps(path)
        data = json.loads(events[0].value_json)
        assert data["cumulative_counter"] == 12500

    def test_non_numeric_steps_skipped(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,NaN,12500"]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_hourly_steps(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500"]
        path = csv_file_factory("steps_2026.csv", lines)
        assert parse_hourly_steps(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("steps_2026.csv", [])
        assert parse_hourly_steps(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,1500,12500"]
        path = csv_file_factory("steps_2026.csv", lines)
        for e in parse_hourly_steps(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Dream quicklog parser
# ──────────────────────────────────────────────────────────────


class TestParseDreamQuicklog:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711278000,07:00:00,-0500,8,positive,flying;ocean;blue,adventure;freedom",
        ]
        path = csv_file_factory("dream_2026.csv", lines)
        events = parse_dream_quicklog(path)
        assert len(events) == 1
        assert events[0].source_module == "behavior.dream"
        assert events[0].event_type == "quick_capture"
        assert events[0].value_numeric == 8.0
        assert events[0].value_text == "flying;ocean;blue"

    def test_vividness_in_json(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,7,neutral,forest,nature"]
        path = csv_file_factory("dream_2026.csv", lines)
        events = parse_dream_quicklog(path)
        data = json.loads(events[0].value_json)
        assert data["vividness"] == 7
        assert data["emotional_tone"] == "neutral"
        assert data["recall_confidence"] == 0.7

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0700,8,positive,dream,theme"]
        path = csv_file_factory("dream_2026.csv", lines)
        events = parse_dream_quicklog(path)
        assert events[0].timezone_offset == "-0700"

    def test_non_numeric_vividness_skipped(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,high,positive,dream,theme"]
        path = csv_file_factory("dream_2026.csv", lines)
        events = parse_dream_quicklog(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,8,positive,keywords"]
        path = csv_file_factory("dream_2026.csv", lines)
        events = parse_dream_quicklog(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("dream_2026.csv", [])
        assert parse_dream_quicklog(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,8,positive,dream,theme"]
        path = csv_file_factory("dream_2026.csv", lines)
        for e in parse_dream_quicklog(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Dream structured parser
# ──────────────────────────────────────────────────────────────


class TestParseDreamStructured:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711278000,07:00:00,-0500,forest;cave,old friend;stranger,running;hiding,fear,work stress",
        ]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        events = parse_dream_structured(path)
        assert len(events) == 1
        assert events[0].source_module == "behavior.dream"
        assert events[0].event_type == "structured_recall"
        assert "forest" in events[0].value_text

    def test_narrative_in_value_text(self, csv_file_factory):
        lines = [
            "1711278000,07:00:00,-0500,library,teacher,reading,calm,school"
        ]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        events = parse_dream_structured(path)
        assert "library" in events[0].value_text
        assert "teacher" in events[0].value_text

    def test_json_structure(self, csv_file_factory):
        lines = [
            "1711278000,07:00:00,-0500,forest,friend,running,fear,anxiety"
        ]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        events = parse_dream_structured(path)
        data = json.loads(events[0].value_json)
        assert "settings" in data
        assert "characters" in data
        assert "actions" in data
        assert data["emotion"] == "fear"
        assert data["waking_connection"] == "anxiety"

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711278000,07:00:00,+0100,park,dog,walking,happy,"]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        events = parse_dream_structured(path)
        assert events[0].timezone_offset == "+0100"

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,forest,friend,running"]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        events = parse_dream_structured(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("dream_detail_2026.csv", [])
        assert parse_dream_structured(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,park,dog,walking,happy,"]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        for e in parse_dream_structured(path):
            assert e.is_valid

    def test_deterministic(self, csv_file_factory):
        lines = ["1711278000,07:00:00,-0500,park,dog,walking,happy,"]
        path = csv_file_factory("dream_detail_2026.csv", lines)
        ids1 = [e.event_id for e in parse_dream_structured(path)]
        ids2 = [e.event_id for e in parse_dream_structured(path)]
        assert ids1 == ids2
