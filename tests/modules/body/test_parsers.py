"""
Tests for modules/body/parsers.py — quicklog, samsung_health, sleep, reaction,
movement/activity/pedometer summaries.
"""

import json

from modules.body.parsers import (
    parse_activity_summary,
    parse_movement_summary,
    parse_pedometer_summary,
    parse_quicklog,
    parse_reaction,
    parse_samsung_health,
    parse_sleep,
)
from tests.conftest import QUICKLOG_CAFFEINE_LINES, QUICKLOG_MEAL_LINES

# ──────────────────────────────────────────────────────────────
# Quicklog parser
# ──────────────────────────────────────────────────────────────


class TestParseQuicklog:
    def test_caffeine_happy_path(self, csv_file_factory):
        path = csv_file_factory("quicklog_2026.csv", QUICKLOG_CAFFEINE_LINES)
        events = parse_quicklog(path)
        assert len(events) == 1
        assert events[0].source_module == "body.caffeine"
        assert events[0].event_type == "intake"
        assert events[0].value_numeric == 200.0
        data = json.loads(events[0].value_json)
        assert data["unit"] == "mg"
        assert data["location"] == "home"

    def test_meal_logged(self, csv_file_factory):
        path = csv_file_factory("quicklog_2026.csv", QUICKLOG_MEAL_LINES)
        events = parse_quicklog(path)
        assert len(events) == 1
        assert events[0].source_module == "body.meal"
        assert events[0].event_type == "logged"
        assert events[0].value_text == "Oatmeal with blueberries"
        assert events[0].value_numeric is None  # meals store text, not numeric

    def test_all_body_categories(self, csv_file_factory):
        """Every body category should produce an event with correct source_module."""
        lines = [
            "1711278000,3-24-26,07:00,1,200,home",       # caffeine
            "1711278060,3-24-26,07:01,10,Eggs,home",      # meal
            "1711278120,3-24-26,07:02,11,mint,home",      # vape
            "1711278180,3-24-26,07:03,12,30,gym",         # exercise
            "1711278240,3-24-26,07:04,13,3,lower back",   # pain
            "1711278300,3-24-26,07:05,17,185,bathroom",   # weight
            "1711278360,3-24-26,07:06,18,120/80,home",    # blood pressure
            "1711278420,3-24-26,07:07,19,16,kitchen",     # water
            "1711278480,3-24-26,07:08,20,Vitamin D,home", # supplement
        ]
        path = csv_file_factory("quicklog_2026.csv", lines)
        events = parse_quicklog(path)
        assert len(events) == 9
        modules = {e.source_module for e in events}
        assert "body.caffeine" in modules
        assert "body.meal" in modules
        assert "body.vape" in modules
        assert "body.exercise" in modules
        assert "body.pain" in modules
        assert "body.weight" in modules
        assert "body.blood_pressure" in modules
        assert "body.water" in modules
        assert "body.supplement" in modules

    def test_non_body_category_skipped(self, csv_file_factory):
        """Category 2 (mood) belongs to Mind module — should be skipped."""
        lines = ["1711278000,3-24-26,07:00,2,7,home"]
        path = csv_file_factory("quicklog_2026.csv", lines)
        events = parse_quicklog(path)
        assert len(events) == 0

    def test_blood_pressure_parsed(self, csv_file_factory):
        lines = ["1711278000,3-24-26,07:00,18,120/80,home"]
        path = csv_file_factory("quicklog_2026.csv", lines)
        events = parse_quicklog(path)
        assert len(events) == 1
        assert events[0].value_text == "120/80"
        assert events[0].value_numeric is None
        data = json.loads(events[0].value_json)
        assert data["systolic"] == 120
        assert data["diastolic"] == 80

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711278000,3-24-26,07:00,1"]
        path = csv_file_factory("quicklog_2026.csv", lines)
        events = parse_quicklog(path)
        assert len(events) == 0

    def test_non_epoch_skipped(self, csv_file_factory):
        lines = ["header,date,time,cat,val,loc"]
        path = csv_file_factory("quicklog_2026.csv", lines)
        events = parse_quicklog(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("quicklog_2026.csv", [])
        assert parse_quicklog(path) == []

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("quicklog_2026.csv", QUICKLOG_CAFFEINE_LINES)
        for e in parse_quicklog(path):
            assert e.is_valid, f"Invalid: {e.validate()}"

    def test_deterministic(self, csv_file_factory):
        path = csv_file_factory("quicklog_2026.csv", QUICKLOG_CAFFEINE_LINES)
        ids1 = [e.event_id for e in parse_quicklog(path)]
        ids2 = [e.event_id for e in parse_quicklog(path)]
        assert ids1 == ids2


# ──────────────────────────────────────────────────────────────
# Samsung Health parser
# ──────────────────────────────────────────────────────────────


class TestParseSamsungHealth:
    def test_steps_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,3-24-26,10:00,1500,samsung_health",
            "1711306800,3-24-26,11:00,2300,samsung_health",
        ]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_samsung_health(path)
        assert len(events) == 2
        assert events[0].source_module == "body.steps"
        assert events[0].event_type == "step_count_samsung"
        assert events[0].value_numeric == 1500.0

    def test_heart_rate(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,72,samsung_health"]
        path = csv_file_factory("hr_2026.csv", lines)
        events = parse_samsung_health(path)
        assert len(events) == 1
        assert events[0].source_module == "body.heart_rate"
        assert events[0].value_numeric == 72.0

    def test_spo2(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,98,samsung_health"]
        path = csv_file_factory("spo2_2026.csv", lines)
        events = parse_samsung_health(path)
        assert len(events) == 1
        assert events[0].source_module == "body.spo2"
        assert events[0].value_numeric == 98.0

    def test_unknown_file_prefix(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,100,samsung_health"]
        path = csv_file_factory("unknown_2026.csv", lines)
        events = parse_samsung_health(path)
        assert events == []

    def test_non_numeric_value_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,NaN,samsung_health"]
        path = csv_file_factory("steps_2026.csv", lines)
        events = parse_samsung_health(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("steps_2026.csv", [])
        assert parse_samsung_health(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,72,samsung_health"]
        path = csv_file_factory("hr_2026.csv", lines)
        for e in parse_samsung_health(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Sleep parser
# ──────────────────────────────────────────────────────────────


class TestParseSleep:
    def test_sleep_start_end(self, csv_file_factory):
        lines = [
            "1711321200,3-24-26,22:00,start,45",
            "1711350000,3-25-26,06:00,end,40",
        ]
        path = csv_file_factory("sleep_2026.csv", lines)
        events = parse_sleep(path)
        assert len(events) == 2
        assert events[0].source_module == "body.sleep"
        assert events[0].event_type == "sleep_start"
        assert events[1].event_type == "sleep_end"

    def test_sleep_start_sleep_end_variants(self, csv_file_factory):
        lines = [
            "1711321200,3-24-26,22:00,sleep_start,45",
            "1711350000,3-25-26,06:00,sleep_end,40",
        ]
        path = csv_file_factory("sleep_2026.csv", lines)
        events = parse_sleep(path)
        assert len(events) == 2
        assert events[0].event_type == "sleep_start"
        assert events[1].event_type == "sleep_end"

    def test_battery_stored(self, csv_file_factory):
        lines = ["1711321200,3-24-26,22:00,start,45"]
        path = csv_file_factory("sleep_2026.csv", lines)
        events = parse_sleep(path)
        assert events[0].value_numeric == 45.0
        data = json.loads(events[0].value_json)
        assert data["battery_pct"] == 45.0

    def test_invalid_event_name_skipped(self, csv_file_factory):
        lines = ["1711321200,3-24-26,22:00,nap,45"]
        path = csv_file_factory("sleep_2026.csv", lines)
        events = parse_sleep(path)
        assert len(events) == 0

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711321200,3-24-26,22:00"]
        path = csv_file_factory("sleep_2026.csv", lines)
        events = parse_sleep(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("sleep_2026.csv", [])
        assert parse_sleep(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711321200,3-24-26,22:00,start,45"]
        path = csv_file_factory("sleep_2026.csv", lines)
        for e in parse_sleep(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Reaction time parser
# ──────────────────────────────────────────────────────────────


class TestParseReaction:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,red,350",
            "1711303201,green,280",
            "1711303202,blue,310",
        ]
        path = csv_file_factory("reaction_2026.csv", lines)
        events = parse_reaction(path)
        assert len(events) == 3
        assert events[0].source_module == "body.cognition"
        assert events[0].event_type == "reaction_time"
        assert events[0].value_numeric == 350.0
        assert events[0].value_text == "red"

    def test_color_in_json(self, csv_file_factory):
        lines = ["1711303200,red,350"]
        path = csv_file_factory("reaction_2026.csv", lines)
        events = parse_reaction(path)
        data = json.loads(events[0].value_json)
        assert data["color"] == "red"
        assert data["unit"] == "ms"

    def test_non_numeric_rt_skipped(self, csv_file_factory):
        lines = ["1711303200,red,NaN"]
        path = csv_file_factory("reaction_2026.csv", lines)
        events = parse_reaction(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,red"]
        path = csv_file_factory("reaction_2026.csv", lines)
        events = parse_reaction(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("reaction_2026.csv", [])
        assert parse_reaction(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,red,350"]
        path = csv_file_factory("reaction_2026.csv", lines)
        for e in parse_reaction(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Sensor summary parsers (DictReader-based)
# ──────────────────────────────────────────────────────────────


class TestParseMovementSummary:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "movement_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_accel_mag,std_accel_mag,"
            "min_accel_mag,max_accel_mag,activity_class,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,9.81,0.15,9.60,10.05,still,60\n"
            "1711303500,3-24-26,10:05,-0500,10.20,0.85,9.10,12.50,walking,60\n"
        )
        events = parse_movement_summary(str(csv))
        assert len(events) == 2
        assert events[0].source_module == "body.movement"
        assert events[0].event_type == "accelerometer_summary"
        assert events[0].value_text == "still"
        assert events[1].value_text == "walking"

    def test_timezone_offset_from_row(self, tmp_path):
        """Verify per-row timezone_offset is used, not a global default."""
        csv = tmp_path / "movement_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_accel_mag,std_accel_mag,"
            "min_accel_mag,max_accel_mag,activity_class,sample_count\n"
            "1711303200,3-24-26,10:00,-0700,9.81,0.15,9.60,10.05,still,60\n"
        )
        events = parse_movement_summary(str(csv))
        assert len(events) == 1
        assert events[0].timezone_offset == "-0700"

    def test_missing_epoch_skipped(self, tmp_path):
        csv = tmp_path / "movement_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_accel_mag,std_accel_mag,"
            "min_accel_mag,max_accel_mag,activity_class,sample_count\n"
            ",3-24-26,10:00,-0500,9.81,0.15,9.60,10.05,still,60\n"
        )
        events = parse_movement_summary(str(csv))
        assert len(events) == 0

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "movement_summary.csv"
        csv.write_text("")
        assert parse_movement_summary(str(csv)) == []

    def test_events_valid(self, tmp_path):
        csv = tmp_path / "movement_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_accel_mag,std_accel_mag,"
            "min_accel_mag,max_accel_mag,activity_class,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,9.81,0.15,9.60,10.05,still,60\n"
        )
        for e in parse_movement_summary(str(csv)):
            assert e.is_valid


class TestParseActivitySummary:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "activity_summary.csv"
        csv.write_text(
            'epoch,date,time,timezone_offset,dominant_activity,activity_counts_json\n'
            '1711303200,3-24-26,10:00,-0500,walking,"{""walking"":45,""still"":15}"\n'
        )
        events = parse_activity_summary(str(csv))
        assert len(events) == 1
        assert events[0].source_module == "body.activity"
        assert events[0].event_type == "classification"
        assert events[0].value_text == "walking"

    def test_timezone_offset_from_row(self, tmp_path):
        csv = tmp_path / "activity_summary.csv"
        csv.write_text(
            'epoch,date,time,timezone_offset,dominant_activity,activity_counts_json\n'
            '1711303200,3-24-26,10:00,-0600,still,"{}"\n'
        )
        events = parse_activity_summary(str(csv))
        assert events[0].timezone_offset == "-0600"

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "activity_summary.csv"
        csv.write_text("")
        assert parse_activity_summary(str(csv)) == []


class TestParsePedometerSummary:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "pedometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,steps_delta,cumulative_steps\n"
            "1711303200,3-24-26,10:00,-0500,150,12500\n"
            "1711303500,3-24-26,10:05,-0500,200,12700\n"
        )
        events = parse_pedometer_summary(str(csv))
        assert len(events) == 2
        assert events[0].source_module == "body.steps"
        assert events[0].event_type == "step_count_sensor"
        assert events[0].value_numeric == 150.0

    def test_zero_steps_skipped(self, tmp_path):
        csv = tmp_path / "pedometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,steps_delta,cumulative_steps\n"
            "1711303200,3-24-26,10:00,-0500,0,12500\n"
        )
        events = parse_pedometer_summary(str(csv))
        assert len(events) == 0

    def test_timezone_offset_from_row(self, tmp_path):
        csv = tmp_path / "pedometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,steps_delta,cumulative_steps\n"
            "1711303200,3-24-26,10:00,+0530,150,12500\n"
        )
        events = parse_pedometer_summary(str(csv))
        assert events[0].timezone_offset == "+0530"

    def test_events_valid(self, tmp_path):
        csv = tmp_path / "pedometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,steps_delta,cumulative_steps\n"
            "1711303200,3-24-26,10:00,-0500,150,12500\n"
        )
        for e in parse_pedometer_summary(str(csv)):
            assert e.is_valid
