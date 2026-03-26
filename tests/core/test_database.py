"""
Tests for core/database.py — SAVEPOINT rollback, deduplication, schema, migrations.
"""

import os
import sqlite3
from datetime import datetime, timezone

import pytest

from core.database import Database
from core.event import Event


# ──────────────────────────────────────────────────────────────
# Schema
# ──────────────────────────────────────────────────────────────


class TestSchema:
    """Verify database schema creation and table structure."""

    def test_events_table_exists(self, db_conn):
        tables = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "events" in tables

    def test_modules_table_exists(self, db_conn):
        tables = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "modules" in tables

    def test_daily_summaries_table_exists(self, db_conn):
        tables = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "daily_summaries" in tables

    def test_correlations_table_exists(self, db_conn):
        tables = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "correlations" in tables

    def test_media_table_exists(self, db_conn):
        tables = {
            row[0]
            for row in db_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "media" in tables

    def test_events_columns(self, db_conn):
        info = db_conn.execute("PRAGMA table_info(events)").fetchall()
        col_names = {row[1] for row in info}
        expected = {
            "event_id",
            "timestamp_utc",
            "timestamp_local",
            "timezone_offset",
            "source_module",
            "event_type",
            "value_numeric",
            "value_text",
            "value_json",
            "tags",
            "location_lat",
            "location_lon",
            "media_ref",
            "confidence",
            "raw_source_id",
            "parser_version",
            "created_at",
        }
        assert expected.issubset(col_names)

    def test_wal_mode_enabled(self, db_conn):
        mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_ensure_schema_idempotent(self, db):
        """Calling ensure_schema twice should not error."""
        db.ensure_schema()
        db.ensure_schema()


# ──────────────────────────────────────────────────────────────
# Event insertion and deduplication
# ──────────────────────────────────────────────────────────────


class TestInsertEvents:
    """Test event insertion via insert_events_for_module."""

    def test_insert_valid_event(self, db, valid_event):
        inserted, skipped = db.insert_events_for_module("device", [valid_event])
        assert inserted == 1
        assert skipped == 0

    def test_insert_counts_match(self, db, valid_event_factory):
        events = [
            valid_event_factory(timestamp_utc=f"2026-03-24T{h:02d}:00:00+00:00")
            for h in range(5)
        ]
        inserted, skipped = db.insert_events_for_module("device", events)
        assert inserted == 5
        assert skipped == 0

    def test_invalid_event_skipped(self, db, valid_event_factory):
        bad = valid_event_factory(source_module="", value_numeric=1.0)
        good = valid_event_factory()
        inserted, skipped = db.insert_events_for_module("device", [bad, good])
        assert inserted == 1
        assert skipped == 1

    def test_dedup_insert_or_replace(self, db, valid_event_factory):
        """Inserting the same event twice yields one row (INSERT OR REPLACE)."""
        e = valid_event_factory()
        db.insert_events_for_module("device", [e])
        db.insert_events_for_module("device", [e])
        count = db.count_events(source_module="device.battery")
        assert count == 1

    def test_dedup_preserves_latest_data(self, db, valid_event_factory):
        """INSERT OR REPLACE keeps the last-written row's data."""
        e1 = valid_event_factory(confidence=0.5)
        e2 = valid_event_factory(confidence=0.9)
        db.insert_events_for_module("device", [e1])
        db.insert_events_for_module("device", [e2])
        rows = db.query_events(source_module="device.battery")
        assert len(rows) == 1
        assert rows[0]["confidence"] == 0.9

    def test_affected_dates_tracked(self, db, valid_event_factory):
        db.reset_affected_dates()
        e = valid_event_factory(timestamp_local="2026-03-24T10:00:00-05:00")
        db.insert_events_for_module("device", [e])
        dates = db.get_affected_dates()
        assert "2026-03-24" in dates

    def test_reset_affected_dates(self, db, valid_event_factory):
        e = valid_event_factory()
        db.insert_events_for_module("device", [e])
        db.reset_affected_dates()
        assert len(db.get_affected_dates()) == 0

    def test_insert_and_retrieve_event(self, db, valid_event):
        """Round-trip: insert an event and query it back with all fields intact."""
        db.insert_events_for_module("device", [valid_event])
        rows = db.query_events(source_module="device.battery")
        assert len(rows) == 1
        row = rows[0]
        assert row["event_id"] == valid_event.event_id
        assert row["timestamp_utc"] == valid_event.timestamp_utc
        assert row["source_module"] == valid_event.source_module
        assert row["event_type"] == valid_event.event_type
        assert row["value_numeric"] == valid_event.value_numeric
        assert row["raw_source_id"] == valid_event.raw_source_id
        assert row["confidence"] == valid_event.confidence

    def test_replace_preserves_event_id(self, db, valid_event_factory):
        """Re-inserting an event with same raw_source_id keeps the same event_id PK."""
        e1 = valid_event_factory(confidence=0.5)
        e2 = valid_event_factory(confidence=0.9)
        # Same defaults → same raw_source_id → same event_id
        assert e1.event_id == e2.event_id

        db.insert_events_for_module("device", [e1])
        db.insert_events_for_module("device", [e2])

        rows = db.query_events(source_module="device.battery")
        assert len(rows) == 1
        assert rows[0]["event_id"] == e1.event_id


# ──────────────────────────────────────────────────────────────
# SAVEPOINT rollback
# ──────────────────────────────────────────────────────────────


class TestSavepointRollback:
    """SAVEPOINT isolation: one module's failure must not affect others."""

    def test_rollback_on_exception(self, db, valid_event_factory):
        """If insertion raises, all events for that module are rolled back."""
        good_event = valid_event_factory(
            source_module="device.battery",
            timestamp_utc="2026-03-24T10:00:00+00:00",
        )
        db.insert_events_for_module("device", [good_event])
        pre_count = db.count_events(source_module="device.battery")
        assert pre_count == 1

        # Create an event that will cause a DB-level error by injecting
        # a bad tuple via monkey-patching
        class BadEvent(Event):
            def to_db_tuple(self):
                raise sqlite3.IntegrityError("simulated failure")

            def validate(self):
                return []

        bad = BadEvent(
            timestamp_utc="2026-03-24T11:00:00+00:00",
            timestamp_local="2026-03-24T06:00:00-05:00",
            timezone_offset="-0500",
            source_module="social.call",
            event_type="incoming",
            value_numeric=120.0,
        )

        with pytest.raises(sqlite3.IntegrityError):
            db.insert_events_for_module("social", [bad])

        # The first module's data should still be there
        assert db.count_events(source_module="device.battery") == 1
        # The failed module's data should be rolled back
        assert db.count_events(source_module="social.call") == 0

    def test_module_isolation(self, db, valid_event_factory):
        """Events from module A survive even when module B fails."""
        # Insert module A events
        events_a = [
            valid_event_factory(
                source_module="device.screen",
                event_type="screen_on",
                value_text="on",
                timestamp_utc=f"2026-03-24T{h:02d}:00:00+00:00",
            )
            for h in range(3)
        ]
        inserted_a, _ = db.insert_events_for_module("device", events_a)
        assert inserted_a == 3

        # Module B insert with forced failure mid-batch
        class FailingEvent(Event):
            def validate(self):
                return []

            def to_db_tuple(self):
                raise RuntimeError("module B crash")

        fail_event = FailingEvent(
            timestamp_utc="2026-03-24T15:00:00+00:00",
            timestamp_local="2026-03-24T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="mind.mood",
            event_type="check_in",
            value_numeric=7.0,
        )

        with pytest.raises(RuntimeError):
            db.insert_events_for_module("mind", [fail_event])

        # Module A events are intact
        assert db.count_events(source_module="device.screen") == 3
        # Module B events are gone
        assert db.count_events(source_module="mind.mood") == 0


# ──────────────────────────────────────────────────────────────
# Migration DDL safety
# ──────────────────────────────────────────────────────────────


class TestMigrationSafety:
    """Only CREATE and ALTER DDL allowed through execute_migration."""

    def test_create_allowed(self, db):
        db.execute_migration(
            "CREATE TABLE IF NOT EXISTS test_table (id TEXT PRIMARY KEY)"
        )
        # Should not raise

    def test_alter_allowed(self, db):
        db.execute_migration(
            "CREATE TABLE IF NOT EXISTS test_alter (id TEXT PRIMARY KEY)"
        )
        db.execute_migration("ALTER TABLE test_alter ADD COLUMN new_col TEXT")

    def test_drop_rejected(self, db):
        with pytest.raises(ValueError, match="DROP"):
            db.execute_migration("DROP TABLE events")

    def test_delete_rejected(self, db):
        with pytest.raises(ValueError, match="DELETE"):
            db.execute_migration("DELETE FROM events WHERE 1=1")

    def test_insert_rejected(self, db):
        with pytest.raises(ValueError, match="INSERT"):
            db.execute_migration("INSERT INTO events (event_id) VALUES ('x')")

    def test_update_rejected(self, db):
        with pytest.raises(ValueError, match="UPDATE"):
            db.execute_migration("UPDATE events SET confidence = 0")

    def test_empty_sql_rejected(self, db):
        with pytest.raises(ValueError):
            db.execute_migration("")


# ──────────────────────────────────────────────────────────────
# Query and count helpers
# ──────────────────────────────────────────────────────────────


class TestQueryHelpers:
    """Test query_events and count_events with filters."""

    def test_count_by_module(self, db, valid_event_factory):
        db.insert_events_for_module(
            "device",
            [
                valid_event_factory(source_module="device.battery"),
            ],
        )
        db.insert_events_for_module(
            "mind",
            [
                valid_event_factory(
                    source_module="mind.mood",
                    event_type="check_in",
                    timestamp_utc="2026-03-24T20:00:00+00:00",
                ),
            ],
        )
        assert db.count_events(source_module="device.battery") == 1
        assert db.count_events(source_module="mind.mood") == 1

    def test_count_by_date(self, db, valid_event_factory):
        db.insert_events_for_module(
            "device",
            [
                valid_event_factory(
                    timestamp_local="2026-03-24T10:00:00-05:00",
                ),
            ],
        )
        assert db.count_events(date="2026-03-24") == 1
        assert db.count_events(date="2026-03-25") == 0

    def test_query_order_injection_fallback(self, db, valid_event_factory):
        """Invalid ORDER BY clause should fall back to default."""
        db.insert_events_for_module("device", [valid_event_factory()])
        # Should not raise even with a malicious order
        rows = db.query_events(order="1; DROP TABLE events--")
        assert len(rows) >= 0

    def test_query_min_confidence(self, db, valid_event_factory):
        db.insert_events_for_module(
            "device",
            [
                valid_event_factory(confidence=0.3),
            ],
        )
        rows_all = db.query_events(min_confidence=0.0)
        rows_high = db.query_events(min_confidence=0.5)
        assert len(rows_all) == 1
        assert len(rows_high) == 0


# ──────────────────────────────────────────────────────────────
# Daily summaries
# ──────────────────────────────────────────────────────────────


class TestDailySummaries:
    """Test upsert_daily_summary."""

    def test_insert_summary(self, db):
        db.upsert_daily_summary(
            "2026-03-24",
            "device.derived",
            "unlock_count",
            value_numeric=42.0,
        )
        row = db.conn.execute(
            "SELECT value_numeric FROM daily_summaries "
            "WHERE date_local = '2026-03-24' AND metric_name = 'unlock_count'"
        ).fetchone()
        assert row[0] == 42.0

    def test_upsert_overwrites(self, db):
        db.upsert_daily_summary(
            "2026-03-24",
            "device.derived",
            "unlock_count",
            value_numeric=42.0,
        )
        db.upsert_daily_summary(
            "2026-03-24",
            "device.derived",
            "unlock_count",
            value_numeric=55.0,
        )
        row = db.conn.execute(
            "SELECT value_numeric FROM daily_summaries "
            "WHERE date_local = '2026-03-24' AND metric_name = 'unlock_count'"
        ).fetchone()
        assert row[0] == 55.0


# ──────────────────────────────────────────────────────────────
# Module status tracking
# ──────────────────────────────────────────────────────────────


class TestModuleStatus:
    """Test update_module_status."""

    def test_success_status(self, db):
        db.update_module_status("device", "Device Module", "1.0.0", success=True)
        row = db.conn.execute(
            "SELECT last_status FROM modules WHERE module_id = 'device'"
        ).fetchone()
        assert row[0] == "success"

    def test_failed_status_with_error(self, db):
        db.update_module_status(
            "device",
            "Device Module",
            "1.0.0",
            success=False,
            error="parse crash",
        )
        row = db.conn.execute(
            "SELECT last_status, last_error FROM modules WHERE module_id = 'device'"
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] == "parse crash"

    def test_upsert_updates_existing(self, db):
        db.update_module_status("device", "Device Module", "1.0.0", success=True)
        db.update_module_status(
            "device", "Device Module", "1.1.0", success=False, error="oops"
        )
        row = db.conn.execute(
            "SELECT version, last_status FROM modules WHERE module_id = 'device'"
        ).fetchone()
        assert row[0] == "1.1.0"
        assert row[1] == "failed"


# ──────────────────────────────────────────────────────────────
# Context manager
# ──────────────────────────────────────────────────────────────


class TestFTSSearch:
    """Full-text search on the events_fts virtual table."""

    def test_fts_search(self, db, valid_event_factory):
        """Insert event with value_text, verify FTS query returns it."""
        e = valid_event_factory(
            value_text="unusual synchronicity at the grocery store",
            source_module="mind.synchronicity",
            event_type="observation",
        )
        db.insert_events_for_module("mind", [e])

        rows = db.conn.execute(
            "SELECT event_id FROM events_fts WHERE events_fts MATCH 'synchronicity'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == e.event_id


# ──────────────────────────────────────────────────────────────
# Concurrent insert safety (WAL mode)
# ──────────────────────────────────────────────────────────────


class TestConcurrentInsertSafety:
    """WAL mode should allow concurrent writes from different threads."""

    def test_concurrent_insert_no_deadlock(self, tmp_path, valid_event_factory):
        import threading

        db_path = str(tmp_path / "concurrent.db")
        errors = []

        def insert_module(module_name, source, n_events):
            try:
                database = Database(db_path)
                database.ensure_schema()
                events = [
                    valid_event_factory(
                        source_module=source,
                        timestamp_utc=f"2026-03-24T{h:02d}:00:00+00:00",
                    )
                    for h in range(n_events)
                ]
                database.insert_events_for_module(module_name, events)
                database.close()
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(
            target=insert_module, args=("device", "device.battery", 5)
        )
        t2 = threading.Thread(
            target=insert_module, args=("environment", "environment.weather", 5)
        )
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Concurrent inserts failed: {errors}"

        # Verify both modules' data landed
        check_db = Database(db_path)
        check_db.ensure_schema()
        assert check_db.count_events(source_module="device.battery") == 5
        assert check_db.count_events(source_module="environment.weather") == 5
        check_db.close()


# ──────────────────────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────────────────────


class TestBackup:
    """Database backup creation and pruning."""

    def test_backup_creates_file(self, tmp_path, valid_event_factory):
        db_path = str(tmp_path / "db" / "lifedata.db")
        database = Database(db_path)
        database.ensure_schema()
        database.insert_events_for_module("device", [valid_event_factory()])

        backup_path = database.backup()
        assert backup_path is not None
        assert os.path.exists(backup_path)
        assert os.path.getsize(backup_path) > 0
        database.close()

    def test_backup_prunes_old(self, tmp_path, valid_event_factory):
        db_path = str(tmp_path / "db" / "lifedata.db")
        database = Database(db_path)
        database.ensure_schema()
        database.insert_events_for_module("device", [valid_event_factory()])

        # Create fake old backups
        backup_dir = os.path.join(tmp_path / "db", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        for i in range(5):
            old_backup = os.path.join(backup_dir, f"lifedata.db.bak.old-{i}")
            with open(old_backup, "w") as f:
                f.write("fake backup")
            # Set mtime to 30 days ago
            old_time = datetime.now(timezone.utc).timestamp() - (30 * 86400)
            os.utime(old_backup, (old_time, old_time))

        database.backup(keep_days=7)

        remaining = os.listdir(backup_dir)
        # Only today's backup should survive; the 5 old ones should be pruned
        assert len(remaining) == 1
        database.close()


# ──────────────────────────────────────────────────────────────
# Context manager
# ──────────────────────────────────────────────────────────────


class TestSchemaMigrations:
    """Versioned schema migration tracking via apply_migrations."""

    def test_apply_migrations_creates_table(self, db):
        """Apply 2 migrations, verify both tables exist."""
        migrations = [
            "CREATE TABLE IF NOT EXISTS mod_alpha (id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS mod_beta (id TEXT PRIMARY KEY, val REAL)",
        ]
        applied = db.apply_migrations("test_mod", migrations)
        assert applied == 2

        tables = {
            row[0]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "mod_alpha" in tables
        assert "mod_beta" in tables

    def test_apply_migrations_skips_already_applied(self, db):
        """Apply 2 migrations, then call again with 3 — only the 3rd runs."""
        migrations_v2 = [
            "CREATE TABLE IF NOT EXISTS skip_a (id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS skip_b (id TEXT PRIMARY KEY)",
        ]
        applied1 = db.apply_migrations("skip_mod", migrations_v2)
        assert applied1 == 2

        migrations_v3 = migrations_v2 + [
            "CREATE TABLE IF NOT EXISTS skip_c (id TEXT PRIMARY KEY)",
        ]
        applied2 = db.apply_migrations("skip_mod", migrations_v3)
        assert applied2 == 1

        tables = {
            row[0]
            for row in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "skip_c" in tables

    def test_apply_migrations_records_version(self, db):
        """Verify schema_versions table has correct entries."""
        migrations = [
            "CREATE TABLE IF NOT EXISTS rec_a (id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS rec_b (id TEXT PRIMARY KEY)",
        ]
        db.apply_migrations("rec_mod", migrations)

        rows = db.conn.execute(
            "SELECT module_id, version, sql_hash FROM schema_versions "
            "WHERE module_id = 'rec_mod' ORDER BY version"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "rec_mod"
        assert rows[0][1] == 0
        assert rows[1][1] == 1
        # Hashes should be non-empty strings
        assert len(rows[0][2]) == 64
        assert len(rows[1][2]) == 64

    def test_get_migration_version_no_migrations(self, db):
        """Returns -1 when no migrations have been applied."""
        assert db.get_migration_version("nonexistent_mod") == -1

    def test_apply_migrations_empty_list(self, db):
        """Empty list is a no-op, returns 0."""
        applied = db.apply_migrations("empty_mod", [])
        assert applied == 0

    def test_migration_idempotent(self, db):
        """Calling apply_migrations twice with same list applies nothing the second time."""
        migrations = [
            "CREATE TABLE IF NOT EXISTS idem_a (id TEXT PRIMARY KEY)",
            "CREATE TABLE IF NOT EXISTS idem_b (id TEXT PRIMARY KEY)",
        ]
        applied1 = db.apply_migrations("idem_mod", migrations)
        assert applied1 == 2

        applied2 = db.apply_migrations("idem_mod", migrations)
        assert applied2 == 0


class TestContextManager:
    def test_context_manager_closes(self, tmp_path):
        db_path = str(tmp_path / "ctx.db")
        with Database(db_path) as database:
            database.ensure_schema()
        # After exit, connection should be closed
        with pytest.raises(Exception):
            database.conn.execute("SELECT 1")
