"""
Tests for SocialModule.post_ingest() derived metrics.

Derived metrics tested:
  - social.derived/density_score: calls*3.0 + SMS*2.0 + notifications*0.1
  - social.derived/digital_hygiene: productive_apps / total_apps * 100
  - social.derived/notification_load: notifications per active hour
"""

import json

import pytest

from core.event import Event
from modules.social import create_module

DATE = "2026-03-20"
DAY_TS = f"{DATE}T23:59:00+00:00"

CONFIG = {
    "lifedata": {
        "modules": {
            "social": {
                "enabled": True,
                "anonymize_contacts": True,
            }
        }
    }
}


def _social_config() -> dict:
    return CONFIG["lifedata"]["modules"]["social"]


def _make_event(
    source_module: str,
    event_type: str,
    timestamp_utc: str = f"{DATE}T12:00:00+00:00",
    timestamp_local: str = f"{DATE}T07:00:00-05:00",
    value_numeric: float | None = None,
    value_text: str | None = None,
    value_json: str | None = None,
) -> Event:
    return Event(
        timestamp_utc=timestamp_utc,
        timestamp_local=timestamp_local,
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        value_json=value_json,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _query_derived(db, event_type: str):
    """Return all derived events of a given type for the test date."""
    rows = db.execute(
        """
        SELECT value_numeric, value_json FROM events
        WHERE source_module = 'social.derived'
          AND event_type = ?
          AND timestamp_utc = ?
        """,
        (event_type, DAY_TS),
    ).fetchall()
    return rows


# ──────────────────────────────────────────────────────────────
# TestDensityScore
# ──────────────────────────────────────────────────────────────


class TestDensityScore:
    """Tests for social.derived/density_score."""

    def test_weighted_calculation(self, db):
        """2 calls + 5 SMS + 20 notifications = 2*3 + 5*2 + 20*0.1 = 18.0."""
        events = []
        # 2 calls
        for i in range(2):
            events.append(
                _make_event(
                    "social.call",
                    "call",
                    timestamp_utc=f"{DATE}T{10+i:02d}:00:00+00:00",
                    timestamp_local=f"{DATE}T{5+i:02d}:00:00-05:00",
                    value_text="incoming",
                )
            )
        # 5 SMS
        for i in range(5):
            events.append(
                _make_event(
                    "social.sms",
                    "message",
                    timestamp_utc=f"{DATE}T{12+i:02d}:00:00+00:00",
                    timestamp_local=f"{DATE}T{7+i:02d}:00:00-05:00",
                    value_text="sms_in",
                )
            )
        # 20 notifications
        for i in range(20):
            events.append(
                _make_event(
                    "social.notification",
                    "received",
                    timestamp_utc=f"{DATE}T{8+i//6:02d}:{(i%6)*10:02d}:00+00:00",
                    timestamp_local=f"{DATE}T{3+i//6:02d}:{(i%6)*10:02d}:00-05:00",
                    value_text=f"notif_{i}",
                )
            )

        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "density_score")
        assert len(rows) == 1
        assert rows[0][0] == 18.0

        meta = json.loads(rows[0][1])
        assert meta["calls"] == 2
        assert meta["sms"] == 5
        assert meta["notifications"] == 20

    def test_zero_interactions_no_event(self, db):
        """No social interactions should produce no density_score event."""
        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "density_score")
        assert len(rows) == 0

    def test_only_notifications_low_score(self, db):
        """Only notifications (no calls or SMS) should yield a low density score."""
        events = []
        for i in range(10):
            events.append(
                _make_event(
                    "social.notification",
                    "received",
                    timestamp_utc=f"{DATE}T{10+i//4:02d}:{(i%4)*15:02d}:00+00:00",
                    timestamp_local=f"{DATE}T{5+i//4:02d}:{(i%4)*15:02d}:00-05:00",
                    value_text=f"notif_{i}",
                )
            )

        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "density_score")
        assert len(rows) == 1
        # 10 * 0.1 = 1.0
        assert rows[0][0] == 1.0

        meta = json.loads(rows[0][1])
        assert meta["calls"] == 0
        assert meta["sms"] == 0
        assert meta["notifications"] == 10

    def test_density_score_value_json_has_weights(self, db):
        """Verify value_json contains calls, sms, notifications, and weights."""
        events = [
            _make_event(
                "social.call",
                "call",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                timestamp_local=f"{DATE}T05:00:00-05:00",
                value_text="outgoing",
            ),
        ]
        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "density_score")
        assert len(rows) == 1
        # 1 call * 3.0 = 3.0
        assert rows[0][0] == 3.0

        meta = json.loads(rows[0][1])
        assert "calls" in meta
        assert "sms" in meta
        assert "notifications" in meta
        assert "weights" in meta
        assert meta["weights"]["call"] == 3.0
        assert meta["weights"]["sms"] == 2.0
        assert meta["weights"]["notification"] == 0.1

    def test_density_custom_weights(self, db):
        """Custom density_score_weights in config should override defaults."""
        events = [
            _make_event(
                "social.call",
                "call",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                timestamp_local=f"{DATE}T05:00:00-05:00",
                value_text="incoming",
            ),
            _make_event(
                "social.sms",
                "message",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                timestamp_local=f"{DATE}T06:00:00-05:00",
                value_text="sms_in",
            ),
        ]
        db.insert_events_for_module("social", events)

        config = _social_config().copy()
        config["density_score_weights"] = {"call": 5.0, "sms": 1.0, "notification": 0.5}
        mod = create_module(config)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "density_score")
        assert len(rows) == 1
        # 1*5.0 + 1*1.0 = 6.0
        assert rows[0][0] == 6.0


# ──────────────────────────────────────────────────────────────
# TestDigitalHygiene
# ──────────────────────────────────────────────────────────────


class TestDigitalHygiene:
    """Tests for social.derived/digital_hygiene."""

    def test_all_productive(self, db):
        """All productive apps should yield 100% hygiene."""
        events = [
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T13:00:00+00:00",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_text="com.android.calendar",
            ),
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                timestamp_local=f"{DATE}T09:00:00-05:00",
                value_text="com.editor.code",
            ),
        ]
        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "digital_hygiene")
        assert len(rows) == 1
        assert rows[0][0] == 100.0

    def test_mixed_apps(self, db):
        """Mix of productive and distraction apps."""
        events = [
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T13:00:00+00:00",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_text="com.android.calendar",
            ),
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                timestamp_local=f"{DATE}T09:00:00-05:00",
                value_text="com.reddit.app",
            ),
        ]
        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "digital_hygiene")
        assert len(rows) == 1
        # 1 productive, 1 distraction, 0 neutral => 50%
        assert rows[0][0] == 50.0

    def test_zero_apps_no_event(self, db):
        """No app usage events should produce no digital_hygiene event."""
        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "digital_hygiene")
        assert len(rows) == 0

    def test_all_distraction_apps(self, db):
        """All distraction apps should yield 0% productive hygiene."""
        events = [
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T13:00:00+00:00",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_text="com.reddit.frontpage",
            ),
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                timestamp_local=f"{DATE}T09:00:00-05:00",
                value_text="com.twitter.android",
            ),
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T15:00:00+00:00",
                timestamp_local=f"{DATE}T10:00:00-05:00",
                value_text="com.youtube.app",
            ),
        ]
        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "digital_hygiene")
        assert len(rows) == 1
        assert rows[0][0] == 0.0

        meta = json.loads(rows[0][1])
        assert meta["productive"] == 0
        assert meta["distraction"] == 3
        assert meta["total_app_switches"] == 3

    def test_hygiene_value_json_fields(self, db):
        """Verify value_json contains productive, distraction, neutral, total_app_switches."""
        events = [
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                timestamp_local=f"{DATE}T05:00:00-05:00",
                value_text="com.android.calendar",
            ),
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                timestamp_local=f"{DATE}T06:00:00-05:00",
                value_text="com.reddit.app",
            ),
            _make_event(
                "social.app_usage",
                "foreground",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                timestamp_local=f"{DATE}T07:00:00-05:00",
                value_text="com.some.randomapp",
            ),
        ]
        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "digital_hygiene")
        assert len(rows) == 1

        meta = json.loads(rows[0][1])
        assert "productive" in meta
        assert "distraction" in meta
        assert "neutral" in meta
        assert "total_app_switches" in meta
        assert "unit" in meta
        assert meta["productive"] == 1
        assert meta["distraction"] == 1
        assert meta["neutral"] == 1
        # 1 productive / 3 total = 33.3%
        assert rows[0][0] == pytest.approx(33.3, abs=0.1)


# ──────────────────────────────────────────────────────────────
# TestNotificationLoad
# ──────────────────────────────────────────────────────────────


class TestNotificationLoad:
    """Tests for social.derived/notification_load."""

    def test_normal_load(self, db):
        """10 notifications over several hours."""
        events = []
        for i in range(10):
            hour_utc = 8 + i // 2
            minute = (i % 2) * 30
            # Local time = UTC - 5 hours (CDT)
            hour_local = hour_utc - 5
            events.append(
                _make_event(
                    "social.notification",
                    "received",
                    timestamp_utc=f"{DATE}T{hour_utc:02d}:{minute:02d}:00+00:00",
                    timestamp_local=f"{DATE}T{hour_local:02d}:{minute:02d}:00-05:00",
                    value_text=f"notif_{i}",
                )
            )

        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "notification_load")
        assert len(rows) == 1

        # notification_load uses timestamp_utc for span calculation
        # First UTC at 08:00, last at 12:30 => 4.5 hours span
        # 10 / 4.5 = 2.222...
        meta = json.loads(rows[0][1])
        assert meta["notifications"] == 10
        assert rows[0][0] == pytest.approx(10.0 / 4.5, abs=0.2)

    def test_zero_notifications_no_event(self, db):
        """No notification events should produce no notification_load event."""
        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "notification_load")
        assert len(rows) == 0

    def test_many_notifications_short_period_high_load(self, db):
        """Many notifications in a short window should produce a high load."""
        events = []
        # 20 notifications within 30 minutes (08:00 to 08:29 UTC)
        for i in range(20):
            events.append(
                _make_event(
                    "social.notification",
                    "received",
                    timestamp_utc=f"{DATE}T08:{i:02d}:00+00:00",
                    timestamp_local=f"{DATE}T03:{i:02d}:00-05:00",
                    value_text=f"burst_notif_{i}",
                )
            )

        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "notification_load")
        assert len(rows) == 1

        # Span: 08:00 to 08:19 = 19 minutes < 1 hour, clamped to 1.0 hour
        # load = 20 / 1.0 = 20.0
        assert rows[0][0] == 20.0

        meta = json.loads(rows[0][1])
        assert meta["notifications"] == 20
        assert meta["active_hours"] == 1.0

    def test_notification_load_value_json_fields(self, db):
        """Verify value_json contains notifications, active_hours, unit."""
        events = []
        for i in range(5):
            events.append(
                _make_event(
                    "social.notification",
                    "received",
                    timestamp_utc=f"{DATE}T{8+i*2:02d}:00:00+00:00",
                    timestamp_local=f"{DATE}T{3+i*2:02d}:00:00-05:00",
                    value_text=f"notif_{i}",
                )
            )

        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "notification_load")
        assert len(rows) == 1

        meta = json.loads(rows[0][1])
        assert "notifications" in meta
        assert "active_hours" in meta
        assert "unit" in meta
        assert meta["unit"] == "notifications_per_hour"
        assert meta["notifications"] == 5
        # 08:00 to 16:00 = 8 hours
        assert meta["active_hours"] == 8.0
        # 5/8 = 0.625 rounded to 0.6
        assert rows[0][0] == pytest.approx(0.6, abs=0.1)

    def test_single_notification_minimum_hour(self, db):
        """A single notification should use minimum 1 hour for active_hours."""
        events = [
            _make_event(
                "social.notification",
                "received",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                timestamp_local=f"{DATE}T07:00:00-05:00",
                value_text="lone_notif",
            ),
        ]
        db.insert_events_for_module("social", events)

        mod = create_module(_social_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "notification_load")
        assert len(rows) == 1
        # Single notification: min=max, span=0, clamped to 1 hour
        # load = 1 / 1.0 = 1.0
        assert rows[0][0] == 1.0
