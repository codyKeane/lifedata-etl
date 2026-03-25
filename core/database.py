"""
LifeData V4 — Database Manager
core/database.py

Manages the SQLite database: schema creation, event insertion with SAVEPOINT
transactions, daily summary support, backup/restore, and query utilities.
"""

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from types import TracebackType
from collections.abc import Sequence
from typing import Optional

from core.event import Event
from core.logger import get_logger

log = get_logger("lifedata.database")

# ──────────────────────────────────────────────────────────────
# Schema DDL — matches LD_MODULE_ALPHA_V4 exactly
# ──────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    timestamp_utc   TEXT NOT NULL,
    timestamp_local TEXT NOT NULL,
    timezone_offset TEXT NOT NULL,
    source_module   TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    value_numeric   REAL,
    value_text      TEXT,
    value_json      TEXT,
    tags            TEXT,
    location_lat    REAL,
    location_lon    REAL,
    media_ref       TEXT,
    confidence      REAL DEFAULT 1.0,
    raw_source_id   TEXT UNIQUE,
    parser_version  TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_time
    ON events(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_events_source
    ON events(source_module);
CREATE INDEX IF NOT EXISTS idx_events_type
    ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_source_time
    ON events(source_module, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_events_tags
    ON events(tags);

CREATE TABLE IF NOT EXISTS modules (
    module_id       TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    version         TEXT NOT NULL,
    enabled         INTEGER DEFAULT 1,
    last_run_utc    TEXT,
    last_status     TEXT,
    last_error      TEXT,
    config_json     TEXT
);

CREATE TABLE IF NOT EXISTS media (
    media_id        TEXT PRIMARY KEY,
    file_path       TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    size_bytes      INTEGER,
    duration_sec    REAL,
    transcript      TEXT,
    thumbnail_path  TEXT,
    created_utc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    date_local      TEXT NOT NULL,
    source_module   TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    value_numeric   REAL,
    value_json      TEXT,
    PRIMARY KEY (date_local, source_module, metric_name)
);

CREATE TABLE IF NOT EXISTS correlations (
    corr_id         TEXT PRIMARY KEY,
    metric_a        TEXT NOT NULL,
    metric_b        TEXT NOT NULL,
    window_days     INTEGER NOT NULL,
    pearson_r       REAL,
    spearman_rho    REAL,
    p_value         REAL,
    n_observations  INTEGER,
    computed_utc    TEXT NOT NULL
);
"""

# FTS5 is created separately because CREATE VIRTUAL TABLE doesn't support IF NOT EXISTS
# the same way. We catch the error if it already exists.
FTS5_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    event_id UNINDEXED,
    tags,
    value_text,
    content='events',
    content_rowid='rowid'
);
"""

FTS5_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(event_id, tags, value_text)
    VALUES (new.event_id, new.tags, new.value_text);
END;
"""

INSERT_EVENT_SQL = """
    INSERT OR REPLACE INTO events
    (event_id, timestamp_utc, timestamp_local, timezone_offset,
     source_module, event_type,
     value_numeric, value_text, value_json, tags,
     location_lat, location_lon, media_ref, confidence,
     raw_source_id, parser_version, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class Database:
    """SQLite database manager for the LifeData V4 events system."""

    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        db_dir = os.path.dirname(self.db_path)
        os.makedirs(db_dir, exist_ok=True)
        os.chmod(db_dir, 0o700)
        self.conn = sqlite3.connect(self.db_path)
        os.chmod(self.db_path, 0o600)
        self.conn.row_factory = sqlite3.Row

        # Performance and safety pragmas
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")

        # Track dates affected during this ETL run for summary recomputation
        self._affected_dates: set[str] = set()

    def ensure_schema(self) -> None:
        """Create all core tables and indexes if they don't exist."""
        self.conn.executescript(SCHEMA_SQL)
        try:
            self.conn.executescript(FTS5_SQL)
            self.conn.executescript(FTS5_TRIGGER_SQL)
        except sqlite3.OperationalError as e:
            # FTS5 may not be available on all SQLite builds
            if "fts5" in str(e).lower():
                log.warning(
                    "FTS5 not available in this SQLite build — "
                    "full-text search will be disabled"
                )
            else:
                raise
        self.conn.commit()
        log.info("Database schema ensured")

    def backup(self, keep_days: int = 7) -> Optional[str]:
        """Create a timestamped backup of the database. Prune old backups.

        Called BEFORE any writes at ETL startup.

        Args:
            keep_days: Number of days of backups to retain.

        Returns:
            Path to the new backup, or None if backup already exists for today.
        """
        if not os.path.exists(self.db_path):
            log.info("No database file to back up yet")
            return None

        backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        os.chmod(backup_dir, 0o700)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        backup_path = os.path.join(backup_dir, f"lifedata.db.bak.{today}")

        if os.path.exists(backup_path):
            log.info(f"Backup already exists for today: {backup_path}")
            return None

        shutil.copy2(self.db_path, backup_path)
        os.chmod(backup_path, 0o600)
        log.info(f"Database backed up to {backup_path}")

        # Prune old backups
        now = datetime.now(timezone.utc).timestamp()
        pruned = 0
        for fname in os.listdir(backup_dir):
            fpath = os.path.join(backup_dir, fname)
            if not os.path.isfile(fpath):
                continue
            age_days = (now - os.path.getmtime(fpath)) / 86400
            if age_days > keep_days:
                os.remove(fpath)
                pruned += 1

        if pruned:
            log.info(f"Pruned {pruned} old backup(s)")

        return backup_path

    def insert_events_for_module(
        self, module_id: str, events: list[Event]
    ) -> tuple[int, int]:
        """Batch insert events for one module, wrapped in a SAVEPOINT.

        On exception, rolls back only this module's writes.
        Other modules are unaffected.

        Args:
            module_id: The module's identifier (for SAVEPOINT naming).
            events: List of Event objects to insert.

        Returns:
            Tuple of (inserted_count, skipped_count).

        Raises:
            Exception: Re-raised after rollback so the orchestrator can log it.
        """
        # Sanitize module_id for use in SQL SAVEPOINT name
        safe_name = "".join(c if c.isalnum() else "_" for c in module_id)
        savepoint = f"sp_{safe_name}"

        inserted = 0
        skipped = 0

        try:
            self.conn.execute(f"SAVEPOINT {savepoint}")

            for event in events:
                errors = event.validate()
                if errors:
                    prov = event.provenance or "unknown"
                    log.warning(
                        f"[{module_id}] Rejected event from {prov}: "
                        f"{'; '.join(errors)}"
                    )
                    skipped += 1
                    continue

                self.conn.execute(INSERT_EVENT_SQL, event.to_db_tuple())
                inserted += 1
                log.debug(
                    f"Ingested {event.event_id[:8]} from "
                    f"{event.provenance or 'unknown'}"
                )

                # Track the date for summary recomputation
                try:
                    date_str = event.timestamp_local[:10]
                    self._affected_dates.add(date_str)
                except (TypeError, IndexError):
                    pass

            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            self.conn.commit()

        except Exception:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise

        return inserted, skipped

    def get_affected_dates(self) -> set[str]:
        """Return all dates affected during this ETL run.

        Used by the orchestrator to pass to compute_daily_summaries()
        so that only changed dates are recomputed.
        """
        return set(self._affected_dates)

    def reset_affected_dates(self) -> None:
        """Clear the affected dates tracker (call at ETL start)."""
        self._affected_dates.clear()

    def update_module_status(
        self,
        module_id: str,
        display_name: str = "",
        version: str = "",
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Update the modules registry with the latest run status."""
        now = datetime.now(timezone.utc).isoformat()
        status = "success" if success else "failed"
        self.conn.execute(
            """
            INSERT INTO modules (module_id, display_name, version, enabled,
                                 last_run_utc, last_status, last_error)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(module_id) DO UPDATE SET
                last_run_utc = excluded.last_run_utc,
                last_status = excluded.last_status,
                last_error = excluded.last_error,
                version = CASE WHEN excluded.version != '' THEN excluded.version
                                ELSE modules.version END
        """,
            (module_id, display_name, version, now, status, error),
        )
        self.conn.commit()

    def count_events(
        self,
        source_module: Optional[str] = None,
        date: Optional[str] = None,
    ) -> int:
        """Count events matching optional filters."""
        query = "SELECT COUNT(*) FROM events WHERE 1=1"
        params: list[str] = []
        if source_module:
            query += " AND source_module = ?"
            params.append(source_module)
        if date:
            query += " AND date(timestamp_local) = ?"
            params.append(date)
        row = self.conn.execute(query, params).fetchone()
        return row[0] if row else 0

    def query_events(
        self,
        source_module: Optional[str] = None,
        event_type: Optional[str] = None,
        start_utc: Optional[str] = None,
        end_utc: Optional[str] = None,
        date: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 1000,
        order: str = "timestamp_utc DESC",
    ) -> list[dict[str, object]]:
        """Flexible event query with optional filters.

        Returns list of dicts (from sqlite3.Row).
        """
        query = "SELECT * FROM events WHERE 1=1"
        params: list[object] = []

        if source_module:
            query += " AND source_module = ?"
            params.append(source_module)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if start_utc:
            query += " AND timestamp_utc >= ?"
            params.append(start_utc)
        if end_utc:
            query += " AND timestamp_utc <= ?"
            params.append(end_utc)
        if date:
            query += " AND date(timestamp_local) = ?"
            params.append(date)
        if min_confidence > 0.0:
            query += " AND confidence >= ?"
            params.append(min_confidence)

        # Validate order to prevent SQL injection
        allowed_orders = {
            "timestamp_utc ASC",
            "timestamp_utc DESC",
            "timestamp_local ASC",
            "timestamp_local DESC",
            "created_at DESC",
        }
        if order not in allowed_orders:
            order = "timestamp_utc DESC"

        query += f" ORDER BY {order} LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    # Allowed first keywords for schema migrations
    _ALLOWED_MIGRATION_DDL = {"CREATE", "ALTER"}

    def execute_migration(self, sql: str) -> sqlite3.Cursor:
        """Execute a DDL-only SQL statement for schema migrations.

        Only CREATE and ALTER statements are permitted. This prevents
        modules from executing arbitrary DML (DROP, DELETE, INSERT, etc.)
        through the migration interface.
        """
        first_word = sql.strip().split()[0].upper() if sql.strip() else ""
        if first_word not in self._ALLOWED_MIGRATION_DDL:
            raise ValueError(
                f"Migration SQL must start with CREATE or ALTER, "
                f"got: '{first_word}' — full SQL rejected for safety"
            )
        log.info(f"Executing migration: {sql[:80]}...")
        return self.conn.execute(sql)

    def execute(self, sql: str, params: Optional[Sequence[object]] = None) -> sqlite3.Cursor:
        """Execute SQL with optional parameters.

        WARNING: This method accepts arbitrary SQL. Callers must validate
        inputs. For schema migrations, use execute_migration() instead.
        """
        if params:
            return self.conn.execute(sql, params)
        return self.conn.execute(sql)

    def upsert_daily_summary(
        self,
        date_local: str,
        source_module: str,
        metric_name: str,
        value_numeric: Optional[float] = None,
        value_json: Optional[str] = None,
    ) -> None:
        """Insert or update a daily summary metric."""
        self.conn.execute(
            """
            INSERT INTO daily_summaries
                (date_local, source_module, metric_name, value_numeric, value_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date_local, source_module, metric_name) DO UPDATE SET
                value_numeric = excluded.value_numeric,
                value_json = excluded.value_json
        """,
            (date_local, source_module, metric_name, value_numeric, value_json),
        )
        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.close()
