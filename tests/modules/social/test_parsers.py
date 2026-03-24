"""
Tests for modules/social/parsers.py — notifications, calls, sms, app_usage, wifi.
"""

import json

from modules.social.parsers import (
    parse_notifications,
    parse_calls,
    parse_sms,
    parse_app_usage,
    parse_wifi,
    _hash_contact,
    _hash_phone,
)
from tests.conftest import (
    NOTIFICATION_LINES,
    CALL_LINES,
    SMS_LINES,
    APP_USAGE_LINES,
)


# ──────────────────────────────────────────────────────────────
# PII hashing
# ──────────────────────────────────────────────────────────────


class TestPIIHashing:
    """Privacy: contact names and phone numbers must be hashed."""

    def test_contact_hash_deterministic(self):
        h1 = _hash_contact("John Doe")
        h2 = _hash_contact("John Doe")
        assert h1 == h2

    def test_contact_hash_is_hex(self):
        h = _hash_contact("John Doe")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_contacts_different_hash(self):
        assert _hash_contact("John Doe") != _hash_contact("Jane Doe")

    def test_empty_contact_returns_unknown(self):
        assert _hash_contact("") == "unknown"

    def test_tasker_variable_returns_unknown(self):
        assert _hash_contact("%CNAME") == "unknown"

    def test_phone_hash_deterministic(self):
        h1 = _hash_phone("+15551234567")
        h2 = _hash_phone("+15551234567")
        assert h1 == h2

    def test_phone_hash_normalizes(self):
        """Spaces, dashes, parens should be stripped before hashing."""
        h1 = _hash_phone("+1 (555) 123-4567")
        h2 = _hash_phone("+15551234567")
        assert h1 == h2

    def test_empty_phone_returns_unknown(self):
        assert _hash_phone("") == "unknown"

    def test_tasker_phone_returns_unknown(self):
        assert _hash_phone("%CNUM") == "unknown"


# ──────────────────────────────────────────────────────────────
# Notifications parser
# ──────────────────────────────────────────────────────────────


class TestParseNotifications:
    def test_valid_notifications(self, csv_file_factory):
        path = csv_file_factory("notifications_2026.csv", NOTIFICATION_LINES)
        events = parse_notifications(path)
        assert len(events) == 2
        assert events[0].source_module == "social.notification"
        assert events[0].event_type == "received"

    def test_app_package_in_json(self, csv_file_factory):
        path = csv_file_factory("notifications_2026.csv", NOTIFICATION_LINES)
        events = parse_notifications(path)
        data = json.loads(events[0].value_json)
        assert data["app"] == "com.slack.android"
        assert data["app_short"] == "android"

    def test_notification_text_truncated(self, csv_file_factory):
        long_text = "x" * 1000
        lines = [f"1711303200,3-24-26,10:00,com.test,{long_text}"]
        path = csv_file_factory("notifications_2026.csv", lines)
        events = parse_notifications(path)
        assert len(events[0].value_text) <= 500

    def test_commas_in_notification_text(self, csv_file_factory):
        """Notification text may contain commas — split on first 4 only."""
        lines = ["1711303200,3-24-26,10:00,com.test,msg with, commas, inside"]
        path = csv_file_factory("notifications_2026.csv", lines)
        events = parse_notifications(path)
        assert len(events) == 1
        assert "commas" in events[0].value_text

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00"]
        path = csv_file_factory("notifications_2026.csv", lines)
        events = parse_notifications(path)
        assert len(events) == 0

    def test_non_epoch_skipped(self, csv_file_factory):
        lines = ["header,line,skip,com.test,text"]
        path = csv_file_factory("notifications_2026.csv", lines)
        events = parse_notifications(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("notifications_2026.csv", [])
        assert parse_notifications(path) == []

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("notifications_2026.csv", NOTIFICATION_LINES)
        for e in parse_notifications(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Calls parser
# ──────────────────────────────────────────────────────────────


class TestParseCalls:
    def test_valid_calls(self, csv_file_factory):
        path = csv_file_factory("calls_2026.csv", CALL_LINES)
        events = parse_calls(path)
        assert len(events) == 2
        assert events[0].source_module == "social.call"

    def test_pii_hashed(self, csv_file_factory):
        path = csv_file_factory("calls_2026.csv", CALL_LINES)
        events = parse_calls(path)
        data = json.loads(events[0].value_json)
        # Contact and phone should be hashed, not plaintext
        assert data["contact_hash"] != "John Doe"
        assert data["phone_hash"] != "+15551234567"
        assert len(data["contact_hash"]) == 16

    def test_duration_stored(self, csv_file_factory):
        path = csv_file_factory("calls_2026.csv", CALL_LINES)
        events = parse_calls(path)
        assert events[0].value_numeric == 180.0

    def test_unresolved_duration_is_none(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,call,+155512345,John,%CDUR"]
        path = csv_file_factory("calls_2026.csv", lines)
        events = parse_calls(path)
        assert events[0].value_numeric is None

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00"]
        path = csv_file_factory("calls_2026.csv", lines)
        events = parse_calls(path)
        assert len(events) == 0

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("calls_2026.csv", CALL_LINES)
        for e in parse_calls(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# SMS parser
# ──────────────────────────────────────────────────────────────


class TestParseSms:
    def test_valid_sms(self, csv_file_factory):
        path = csv_file_factory("sms_2026.csv", SMS_LINES)
        events = parse_sms(path)
        assert len(events) == 2
        assert events[0].source_module == "social.sms"
        assert events[0].event_type == "sms_in"
        assert events[1].event_type == "sms_out"

    def test_phone_hashed(self, csv_file_factory):
        path = csv_file_factory("sms_2026.csv", SMS_LINES)
        events = parse_sms(path)
        assert events[0].value_text != "+15551234567"
        assert len(events[0].value_text) == 16

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00"]
        path = csv_file_factory("sms_2026.csv", lines)
        events = parse_sms(path)
        assert len(events) == 0

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("sms_2026.csv", SMS_LINES)
        for e in parse_sms(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# App usage parser
# ──────────────────────────────────────────────────────────────


class TestParseAppUsage:
    def test_valid_app_usage(self, csv_file_factory):
        path = csv_file_factory("app_usage_2026.csv", APP_USAGE_LINES)
        events = parse_app_usage(path)
        assert len(events) == 2
        assert events[0].source_module == "social.app_usage"
        assert events[0].event_type == "foreground"
        assert events[0].value_text == "com.slack.android"

    def test_non_epoch_skipped(self, csv_file_factory):
        lines = ["not_a_number,3-24-26,10:00,com.test,%APP"]
        path = csv_file_factory("app_usage_2026.csv", lines)
        events = parse_app_usage(path)
        assert len(events) == 0

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("app_usage_2026.csv", APP_USAGE_LINES)
        for e in parse_app_usage(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# WiFi parser
# ──────────────────────────────────────────────────────────────


class TestParseWifi:
    def test_valid_wifi(self, csv_file_factory):
        lines = [
            "1711303200,3-24-26,10:00,connected,MyWiFi",
            "1711306800,3-24-26,11:00,disconnected,MyWiFi",
        ]
        path = csv_file_factory("wifi_2026.csv", lines)
        events = parse_wifi(path)
        assert len(events) == 2
        assert events[0].source_module == "social.wifi"
        assert events[0].event_type == "connected"
        assert events[1].event_type == "disconnected"

    def test_invalid_state_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,scanning,MyWiFi"]
        path = csv_file_factory("wifi_2026.csv", lines)
        events = parse_wifi(path)
        assert len(events) == 0

    def test_multiline_wifi_data_ignored(self, csv_file_factory):
        """Non-epoch lines (WiFi scan data) should be ignored."""
        lines = [
            "1711303200,3-24-26,10:00,connected,MyWiFi",
            ">>> SCAN <<<",
            "SSID: Neighbor",
            "Signal: -67dBm",
            "1711306800,3-24-26,11:00,disconnected,MyWiFi",
        ]
        path = csv_file_factory("wifi_2026.csv", lines)
        events = parse_wifi(path)
        assert len(events) == 2

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("wifi_2026.csv", [])
        assert parse_wifi(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = [
            "1711303200,3-24-26,10:00,connected,MyWiFi",
        ]
        path = csv_file_factory("wifi_2026.csv", lines)
        for e in parse_wifi(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Cross-parser deduplication determinism
# ──────────────────────────────────────────────────────────────


class TestSocialDeduplication:
    def test_notifications_deterministic(self, csv_file_factory):
        path = csv_file_factory("notifications_2026.csv", NOTIFICATION_LINES)
        ids1 = [e.event_id for e in parse_notifications(path)]
        ids2 = [e.event_id for e in parse_notifications(path)]
        assert ids1 == ids2

    def test_calls_deterministic(self, csv_file_factory):
        path = csv_file_factory("calls_2026.csv", CALL_LINES)
        ids1 = [e.event_id for e in parse_calls(path)]
        ids2 = [e.event_id for e in parse_calls(path)]
        assert ids1 == ids2

    def test_sms_deterministic(self, csv_file_factory):
        path = csv_file_factory("sms_2026.csv", SMS_LINES)
        ids1 = [e.event_id for e in parse_sms(path)]
        ids2 = [e.event_id for e in parse_sms(path)]
        assert ids1 == ids2
