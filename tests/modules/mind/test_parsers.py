"""
Tests for modules/mind/parsers.py — morning and evening check-in parsers.
"""

import json

from modules.mind.parsers import parse_morning, parse_evening
from tests.conftest import MORNING_LINES, EVENING_LINES


# ──────────────────────────────────────────────────────────────
# Morning parser
# ──────────────────────────────────────────────────────────────


class TestParseMorning:
    def test_valid_morning(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", MORNING_LINES)
        events = parse_morning(path)
        # Each row emits: 1 assessment + up to 3 individual (sleep, mood, energy)
        assert len(events) >= 6  # 2 rows × (1 + 3)

    def test_assessment_event(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", MORNING_LINES)
        events = parse_morning(path)
        assessments = [e for e in events if e.event_type == "assessment"]
        assert len(assessments) == 2
        assert assessments[0].source_module == "mind.morning"

        data = json.loads(assessments[0].value_json)
        assert data["sleep_quality"] == 8.0
        assert data["mood"] == 7.0
        assert data["energy"] == 6.0

    def test_individual_checkins(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", MORNING_LINES[:1])
        events = parse_morning(path)
        modules = {e.source_module for e in events}
        assert "mind.sleep" in modules
        assert "mind.mood" in modules
        assert "mind.energy" in modules

    def test_mood_value(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", MORNING_LINES[:1])
        events = parse_morning(path)
        mood = [e for e in events if e.source_module == "mind.mood"][0]
        assert mood.value_numeric == 7.0
        assert mood.value_text == "morning"

    def test_manual_entry_detection(self, csv_file_factory):
        lines = ["1711278000,3-24-26,07:00,8,1,7,6,manual"]
        path = csv_file_factory("morning_2026.csv", lines)
        events = parse_morning(path)
        assert any("manual" in (e.tags or "") for e in events)

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711278000,3-24-26,07:00,8,1"]
        path = csv_file_factory("morning_2026.csv", lines)
        events = parse_morning(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", [])
        assert parse_morning(path) == []

    def test_non_epoch_header_skipped(self, csv_file_factory):
        lines = ["epoch,date,time,sleep,dream,mood,energy"] + MORNING_LINES
        path = csv_file_factory("morning_2026.csv", lines)
        events = parse_morning(path)
        assessments = [e for e in events if e.event_type == "assessment"]
        assert len(assessments) == 2  # header ignored

    def test_non_numeric_scores(self, csv_file_factory):
        """Non-numeric score fields parsed via safe_float → None."""
        lines = ["1711278000,3-24-26,07:00,good,yes,happy,great"]
        path = csv_file_factory("morning_2026.csv", lines)
        events = parse_morning(path)
        # Assessment still created (has value_json), individual check_ins with None skipped
        assessments = [e for e in events if e.event_type == "assessment"]
        assert len(assessments) == 1

    def test_all_events_valid(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", MORNING_LINES)
        for e in parse_morning(path):
            assert e.is_valid, f"Invalid: {e.validate()}"

    def test_deterministic_ids(self, csv_file_factory):
        path = csv_file_factory("morning_2026.csv", MORNING_LINES)
        run1 = parse_morning(path)
        run2 = parse_morning(path)
        assert [e.event_id for e in run1] == [e.event_id for e in run2]


# ──────────────────────────────────────────────────────────────
# Evening parser
# ──────────────────────────────────────────────────────────────


class TestParseEvening:
    def test_valid_evening(self, csv_file_factory):
        path = csv_file_factory("evening_2026.csv", EVENING_LINES)
        events = parse_evening(path)
        # Each row: 1 assessment + up to 4 individual (mood, stress, productivity, social)
        assert len(events) >= 6

    def test_assessment_event(self, csv_file_factory):
        path = csv_file_factory("evening_2026.csv", EVENING_LINES[:1])
        events = parse_evening(path)
        assessment = [e for e in events if e.event_type == "assessment"][0]
        assert assessment.source_module == "mind.evening"
        data = json.loads(assessment.value_json)
        assert data["day_rating"] == 7.0
        assert data["stress"] == 3.0

    def test_stress_checkin(self, csv_file_factory):
        path = csv_file_factory("evening_2026.csv", EVENING_LINES[:1])
        events = parse_evening(path)
        stress = [e for e in events if e.source_module == "mind.stress"]
        assert len(stress) == 1
        assert stress[0].value_numeric == 3.0

    def test_productivity_checkin(self, csv_file_factory):
        path = csv_file_factory("evening_2026.csv", EVENING_LINES[:1])
        events = parse_evening(path)
        prod = [e for e in events if e.source_module == "mind.productivity"]
        assert len(prod) == 1
        assert prod[0].value_numeric == 8.0

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711321200,3-24-26,22:00,7,3"]
        path = csv_file_factory("evening_2026.csv", lines)
        events = parse_evening(path)
        assert len(events) == 0

    def test_manual_tag(self, csv_file_factory):
        lines = ["1711321200,3-24-26,22:00,7,3,8,6,manual"]
        path = csv_file_factory("evening_2026.csv", lines)
        events = parse_evening(path)
        assert any("manual" in (e.tags or "") for e in events)

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("evening_2026.csv", [])
        assert parse_evening(path) == []

    def test_all_events_valid(self, csv_file_factory):
        path = csv_file_factory("evening_2026.csv", EVENING_LINES)
        for e in parse_evening(path):
            assert e.is_valid
