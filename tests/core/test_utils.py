"""
Tests for core/utils.py — timestamp parsing, safe conversions, file discovery.
"""

import json
import os
import pytest

from core.utils import (
    parse_timestamp,
    format_offset,
    safe_float,
    safe_int,
    safe_json,
    glob_files,
    today_local,
    now_utc_iso,
)


# ──────────────────────────────────────────────────────────────
# parse_timestamp
# ──────────────────────────────────────────────────────────────


class TestParseTimestamp:
    """Test timestamp parsing across all supported formats."""

    def test_epoch_seconds(self):
        utc, local = parse_timestamp("1711303200", "-0500")
        assert "2024-03-24" in utc
        assert utc.endswith("+00:00")

    def test_epoch_milliseconds(self):
        utc, local = parse_timestamp("1711303200000", "-0500")
        assert "2024-03-24" in utc

    def test_iso_8601_with_tz(self):
        utc, local = parse_timestamp("2026-03-24T15:00:00-05:00", "-0500")
        assert "2026-03-24T20:00:00" in utc

    def test_iso_8601_zulu(self):
        utc, local = parse_timestamp("2026-03-24T15:00:00Z", "-0500")
        assert "2026-03-24T15:00:00" in utc

    def test_local_datetime_string(self):
        utc, local = parse_timestamp("2026-03-24 10:00:00", "-0500")
        # 10:00 local at -0500 → 15:00 UTC
        assert "15:00:00" in utc

    def test_local_datetime_no_seconds(self):
        utc, local = parse_timestamp("2026-03-24 10:00", "-0500")
        assert "15:00" in utc

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_timestamp("not-a-timestamp", "-0500")

    def test_negative_epoch(self):
        """Negative epochs (pre-1970) should still parse."""
        utc, local = parse_timestamp("-86400", "-0500")
        assert "1969" in utc

    def test_whitespace_stripped(self):
        utc, local = parse_timestamp("  1711303200  ", "-0500")
        assert "2024-03-24" in utc

    def test_bad_tz_offset_falls_back(self):
        """Invalid tz_offset should fall back to CST (-5)."""
        utc, local = parse_timestamp("2026-03-24 10:00:00", "garbage")
        # Fallback to -5, so 10:00 local → 15:00 UTC
        assert "15:00:00" in utc

    def test_parse_timestamp_dst_spring_forward(self):
        """March DST transition: clocks spring forward, offset changes -0600 → -0500."""
        # 2026-03-08 is DST spring-forward in US Central
        # At 2:00 AM CST, clocks move to 3:00 AM CDT
        # Before DST: 01:00 CST (-0600) = 07:00 UTC
        utc_before, _ = parse_timestamp("2026-03-08 01:00:00", "-0600")
        assert "07:00:00" in utc_before

        # After DST: 03:00 CDT (-0500) = 08:00 UTC
        utc_after, _ = parse_timestamp("2026-03-08 03:00:00", "-0500")
        assert "08:00:00" in utc_after

    def test_parse_timestamp_dst_fall_back(self):
        """November DST transition: clocks fall back, offset changes -0500 → -0600."""
        # 2026-11-01 is DST fall-back in US Central
        # At 2:00 AM CDT, clocks move to 1:00 AM CST
        # Before fallback: 01:00 CDT (-0500) = 06:00 UTC
        utc_before, _ = parse_timestamp("2026-11-01 01:00:00", "-0500")
        assert "06:00:00" in utc_before

        # After fallback: 01:00 CST (-0600) = 07:00 UTC (same wall clock, different UTC)
        utc_after, _ = parse_timestamp("2026-11-01 01:00:00", "-0600")
        assert "07:00:00" in utc_after


# ──────────────────────────────────────────────────────────────
# format_offset
# ──────────────────────────────────────────────────────────────


class TestFormatOffset:
    def test_already_normalized(self):
        assert format_offset("-0500") == "-0500"

    def test_short_form(self):
        assert format_offset("-5") == "-0500"

    def test_three_char(self):
        assert format_offset("-05") == "-0500"

    def test_colon_stripped(self):
        assert format_offset("+05:30") == "+0530"

    def test_whitespace_stripped(self):
        assert format_offset("  -0500  ") == "-0500"


# ──────────────────────────────────────────────────────────────
# safe_float
# ──────────────────────────────────────────────────────────────


class TestSafeFloat:
    def test_valid_float(self):
        assert safe_float("3.14") == 3.14

    def test_valid_int_string(self):
        assert safe_float("42") == 42.0

    def test_none_returns_none(self):
        assert safe_float(None) is None

    def test_empty_string_returns_none(self):
        assert safe_float("") is None

    def test_nan_returns_none(self):
        assert safe_float(float("nan")) is None

    def test_inf_returns_none(self):
        assert safe_float(float("inf")) is None

    def test_negative_inf_returns_none(self):
        assert safe_float(float("-inf")) is None

    def test_non_numeric_string(self):
        assert safe_float("hello") is None

    def test_tasker_variable_returns_none(self):
        assert safe_float("%TEMP") is None

    def test_zero(self):
        assert safe_float("0") == 0.0

    def test_negative(self):
        assert safe_float("-7.5") == -7.5


# ──────────────────────────────────────────────────────────────
# safe_int
# ──────────────────────────────────────────────────────────────


class TestSafeInt:
    def test_valid_int(self):
        assert safe_int("42") == 42

    def test_float_string_truncates(self):
        assert safe_int("3.7") == 3

    def test_none_returns_none(self):
        assert safe_int(None) is None

    def test_non_numeric(self):
        assert safe_int("abc") is None

    def test_tasker_variable(self):
        assert safe_int("%MFREE") is None


# ──────────────────────────────────────────────────────────────
# safe_json
# ──────────────────────────────────────────────────────────────


class TestSafeJson:
    def test_dict_serialized(self):
        result = safe_json({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_none_returns_empty_object(self):
        assert safe_json(None) == "{}"

    def test_non_serializable_uses_str(self):
        """Non-serializable types should be converted via default=str."""
        from datetime import datetime

        result = safe_json({"dt": datetime(2026, 3, 24)})
        parsed = json.loads(result)
        assert "2026" in parsed["dt"]

    def test_nested_structure(self):
        data = {"a": [1, 2, {"b": True}]}
        result = safe_json(data)
        assert json.loads(result) == data


# ──────────────────────────────────────────────────────────────
# glob_files
# ──────────────────────────────────────────────────────────────


class TestGlobFiles:
    def test_finds_csv_files(self, tmp_path):
        (tmp_path / "a.csv").write_text("data")
        (tmp_path / "b.csv").write_text("data")
        (tmp_path / "c.txt").write_text("data")
        files = glob_files(str(tmp_path), "*.csv")
        assert len(files) == 2
        assert all(f.endswith(".csv") for f in files)

    def test_recursive_search(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.csv").write_text("data")
        files = glob_files(str(tmp_path), "*.csv", recursive=True)
        assert len(files) == 1

    def test_non_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.csv").write_text("data")
        (tmp_path / "top.csv").write_text("data")
        files = glob_files(str(tmp_path), "*.csv", recursive=False)
        assert len(files) == 1

    def test_path_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="must not contain"):
            glob_files(str(tmp_path), "../../../etc/passwd")

    def test_absolute_pattern_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="must not contain"):
            glob_files(str(tmp_path), "/etc/passwd")

    def test_results_sorted(self, tmp_path):
        for name in ["c.csv", "a.csv", "b.csv"]:
            (tmp_path / name).write_text("data")
        files = glob_files(str(tmp_path), "*.csv")
        basenames = [os.path.basename(f) for f in files]
        assert basenames == sorted(basenames)

    def test_empty_directory(self, tmp_path):
        files = glob_files(str(tmp_path), "*.csv")
        assert files == []


# ──────────────────────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────────────────────


class TestMiscUtils:
    def test_today_local_format(self):
        result = today_local("America/Chicago")
        assert len(result) == 10
        assert result[4] == "-"

    def test_now_utc_iso_format(self):
        result = now_utc_iso()
        assert "T" in result
        assert "+00:00" in result
