"""
Tests for modules/oracle/parsers.py — iching, rng, schumann, planetary_hours.
"""

import json

from modules.oracle.parsers import (
    parse_iching_auto,
    parse_iching_casting,
    parse_planetary_hours,
    parse_rng_raw,
    parse_rng_samples,
    parse_schumann,
)

# ──────────────────────────────────────────────────────────────
# I Ching casting parser
# ──────────────────────────────────────────────────────────────


class TestParseIchingCasting:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,1,Force (Qian),7|7|7|7|7|7,none,1,Force (Qian)",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        assert len(events) == 1
        assert events[0].source_module == "oracle.iching"
        assert events[0].event_type == "casting"
        assert events[0].value_numeric == 1.0
        assert events[0].value_text == "Force (Qian)"

    def test_changing_lines_produce_moving_events(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,1,Force (Qian),9|7|7|6|7|7,1|4,44,Coupling (Gou)",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        castings = [e for e in events if e.event_type == "casting"]
        moving = [e for e in events if e.event_type == "moving_line"]
        assert len(castings) == 1
        assert len(moving) == 2
        assert moving[0].value_numeric == 1.0  # line position
        assert "yang" in moving[0].value_text  # 9 → yang → yin

    def test_question_hash_privacy(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,1,Force (Qian),7|7|7|7|7|7,none,1,Force (Qian),What should I do?",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        data = json.loads(events[0].value_json)
        assert data["question_hash"] is not None
        assert data["question_hash"] != "What should I do?"  # hashed
        assert len(data["question_hash"]) == 16

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0700,coins,1,Force,7|7|7|7|7|7,none,1,Force",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        assert events[0].timezone_offset == "-0700"

    def test_invalid_hex_num_skipped(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,0,Invalid,7|7|7|7|7|7,none,0,Invalid",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        assert len(events) == 0

    def test_hex_num_65_skipped(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,65,Bad,7|7|7|7|7|7,none,65,Bad",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,coins,1"]
        path = csv_file_factory("iching_2026.csv", lines)
        events = parse_iching_casting(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("iching_2026.csv", [])
        assert parse_iching_casting(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,1,Force (Qian),7|7|7|7|7|7,none,1,Force (Qian)",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        for e in parse_iching_casting(path):
            assert e.is_valid

    def test_deterministic(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,coins,1,Force (Qian),7|7|7|7|7|7,none,1,Force (Qian)",
        ]
        path = csv_file_factory("iching_2026.csv", lines)
        ids1 = [e.event_id for e in parse_iching_casting(path)]
        ids2 = [e.event_id for e in parse_iching_casting(path)]
        assert ids1 == ids2


# ──────────────────────────────────────────────────────────────
# I Ching auto parser
# ──────────────────────────────────────────────────────────────


class TestParseIchingAuto:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,yarrow,11,Pervading (Tai),7|8|7|8|7|8,none,11,Pervading (Tai)",
        ]
        path = csv_file_factory("iching_auto_2026.csv", lines)
        events = parse_iching_auto(path)
        assert len(events) == 1
        assert events[0].event_type == "casting"
        data = json.loads(events[0].value_json)
        assert data["automated"] is True

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500"]
        path = csv_file_factory("iching_auto_2026.csv", lines)
        assert parse_iching_auto(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("iching_auto_2026.csv", [])
        assert parse_iching_auto(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,yarrow,11,Pervading (Tai),7|8|7|8|7|8,none,11,Pervading (Tai)",
        ]
        path = csv_file_factory("iching_auto_2026.csv", lines)
        for e in parse_iching_auto(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# RNG samples parser
# ──────────────────────────────────────────────────────────────


class TestParseRngSamples:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00:00,-0500,128.5,0.15",
            "1711306800,11:00:00,-0500,126.0,-0.22",
        ]
        path = csv_file_factory("rng_2026.csv", lines)
        events = parse_rng_samples(path)
        assert len(events) == 2
        assert events[0].source_module == "oracle.rng"
        assert events[0].event_type == "hardware_sample"
        assert events[0].value_numeric == 128.5

    def test_z_score_in_json(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,128.5,0.15"]
        path = csv_file_factory("rng_2026.csv", lines)
        events = parse_rng_samples(path)
        data = json.loads(events[0].value_json)
        assert data["z_score"] == 0.15
        assert data["expected_mean"] == 127.5

    def test_timezone_offset_from_row(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0800,128.5,0.15"]
        path = csv_file_factory("rng_2026.csv", lines)
        events = parse_rng_samples(path)
        assert events[0].timezone_offset == "-0800"

    def test_non_numeric_mean_skipped(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,NaN,NaN"]
        path = csv_file_factory("rng_2026.csv", lines)
        events = parse_rng_samples(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500"]
        path = csv_file_factory("rng_2026.csv", lines)
        assert parse_rng_samples(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("rng_2026.csv", [])
        assert parse_rng_samples(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00:00,-0500,128.5,0.15"]
        path = csv_file_factory("rng_2026.csv", lines)
        for e in parse_rng_samples(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# RNG raw parser
# ──────────────────────────────────────────────────────────────


class TestParseRngRaw:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "rng_raw_1711303200.csv"
        values = ",".join(str(v) for v in range(100))
        csv.write_text(values)
        events = parse_rng_raw(str(csv))
        assert len(events) == 1
        assert events[0].source_module == "oracle.rng"
        assert events[0].event_type == "raw_batch"
        data = json.loads(events[0].value_json)
        assert data["n_bytes"] == 100

    def test_stats_computed(self, tmp_path):
        csv = tmp_path / "rng_raw_1711303200.csv"
        csv.write_text("0,128,255")
        events = parse_rng_raw(str(csv))
        data = json.loads(events[0].value_json)
        assert data["min"] == 0
        assert data["max"] == 255
        assert data["n_bytes"] == 3

    def test_bad_filename_returns_empty(self, tmp_path):
        csv = tmp_path / "rng_raw_notepoch.csv"
        csv.write_text("100,200,150")
        events = parse_rng_raw(str(csv))
        assert events == []

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "rng_raw_1711303200.csv"
        csv.write_text("")
        events = parse_rng_raw(str(csv))
        assert events == []

    def test_events_valid(self, tmp_path):
        csv = tmp_path / "rng_raw_1711303200.csv"
        csv.write_text("100,200,150")
        for e in parse_rng_raw(str(csv)):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Schumann resonance parser
# ──────────────────────────────────────────────────────────────


class TestParseSchumann:
    def test_happy_path(self, tmp_path):
        data = {
            "fetched_utc": "2026-03-24T10:00:00Z",
            "source": "heartmath",
            "fundamental_hz": 7.85,
            "amplitude": 1.2,
            "q_factor": 5.5,
            "harmonics": [14.3, 20.8],
            "quality": "good",
        }
        path = tmp_path / "schumann_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_schumann(str(path))
        assert len(events) == 1  # no excursion (7.85 within 0.5 of 7.83)
        assert events[0].source_module == "oracle.schumann"
        assert events[0].event_type == "measurement"
        assert events[0].value_numeric == 7.85

    def test_excursion_generated(self, tmp_path):
        """Deviation > 0.5 Hz from 7.83 baseline should produce excursion event."""
        data = {
            "fetched_utc": "2026-03-24T10:00:00Z",
            "source": "heartmath",
            "fundamental_hz": 8.5,
        }
        path = tmp_path / "schumann_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_schumann(str(path))
        assert len(events) == 2
        excursion = [e for e in events if e.event_type == "excursion"]
        assert len(excursion) == 1
        assert excursion[0].value_numeric > 0

    def test_array_of_measurements(self, tmp_path):
        data = [
            {"fetched_utc": "2026-03-24T10:00:00Z", "source": "heartmath", "fundamental_hz": 7.83},
            {"fetched_utc": "2026-03-24T11:00:00Z", "source": "tomsk", "fundamental_hz": 7.80},
        ]
        path = tmp_path / "schumann_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_schumann(str(path))
        assert len(events) == 2

    def test_missing_fetched_utc_skipped(self, tmp_path):
        data = {"source": "heartmath", "fundamental_hz": 7.83}
        path = tmp_path / "schumann_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_schumann(str(path))
        assert len(events) == 0

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "schumann_2026-03-24.json"
        path.write_text("not json")
        assert parse_schumann(str(path)) == []

    def test_events_valid(self, tmp_path):
        data = {
            "fetched_utc": "2026-03-24T10:00:00Z",
            "source": "heartmath",
            "fundamental_hz": 7.83,
        }
        path = tmp_path / "schumann_2026-03-24.json"
        path.write_text(json.dumps(data))
        for e in parse_schumann(str(path)):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Planetary hours parser
# ──────────────────────────────────────────────────────────────


class TestParsePlanetaryHours:
    def test_happy_path(self, tmp_path):
        data = {
            "date": "2026-03-24",
            "day_ruler": "Mars",
            "weekday": "Tuesday",
            "sunrise": "2026-03-24T06:30:00-05:00",
            "sunset": "2026-03-24T18:45:00-05:00",
            "hours": [
                {
                    "hour_number": 1,
                    "is_night": False,
                    "ruling_planet": "Mars",
                    "start_time": "2026-03-24T06:30:00-05:00",
                    "end_time": "2026-03-24T07:31:00-05:00",
                    "duration_minutes": 61.25,
                },
                {
                    "hour_number": 2,
                    "is_night": False,
                    "ruling_planet": "Sun",
                    "start_time": "2026-03-24T07:31:00-05:00",
                    "end_time": "2026-03-24T08:32:00-05:00",
                    "duration_minutes": 61.25,
                },
            ],
        }
        path = tmp_path / "hours_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_planetary_hours(str(path))
        # 1 day_ruler + 2 hours = 3 events
        day_rulers = [e for e in events if e.event_type == "day_ruler"]
        hours = [e for e in events if e.event_type == "current_hour"]
        assert len(day_rulers) == 1
        assert day_rulers[0].value_text == "Mars"
        assert len(hours) == 2
        assert hours[0].value_text == "Mars"
        assert hours[1].value_text == "Sun"

    def test_missing_date_returns_empty(self, tmp_path):
        data = {"day_ruler": "Mars", "hours": []}
        path = tmp_path / "hours_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_planetary_hours(str(path))
        assert events == []

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "hours_2026-03-24.json"
        path.write_text("bad json")
        assert parse_planetary_hours(str(path)) == []

    def test_events_valid(self, tmp_path):
        data = {
            "date": "2026-03-24",
            "day_ruler": "Mars",
            "sunrise": "2026-03-24T06:30:00-05:00",
            "sunset": "2026-03-24T18:45:00-05:00",
            "hours": [
                {
                    "hour_number": 1,
                    "is_night": False,
                    "ruling_planet": "Mars",
                    "start_time": "2026-03-24T06:30:00-05:00",
                    "end_time": "2026-03-24T07:31:00-05:00",
                    "duration_minutes": 61.25,
                }
            ],
        }
        path = tmp_path / "hours_2026-03-24.json"
        path.write_text(json.dumps(data))
        for e in parse_planetary_hours(str(path)):
            assert e.is_valid
