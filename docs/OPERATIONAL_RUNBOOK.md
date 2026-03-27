# LifeData V4 -- Operational Runbook

Practical procedures for operating, maintaining, and recovering the LifeData ETL pipeline.

---

## 1. Daily Operations

### 1.1 Expected Cron Schedule

The ETL runs nightly at 23:55 local time. Verify the crontab entry:

```bash
crontab -l | grep run_etl
# Expected:
# 55 23 * * * cd ~/LifeData && venv/bin/python run_etl.py --report
```

Additional scheduled jobs (set up separately via cron or systemd timers):

| Job | Schedule | Command |
|-----|----------|---------|
| ETL + daily report | `55 23 * * *` | `run_etl.py --report` |
| News fetch | `0 */4 * * *` | `scripts/fetch_news.py` |
| Astro/planetary | `0 5 * * *` | `scripts/compute_planetary_hours.py` |
| Weekly report | `0 1 * * 1` | `run_etl.py --weekly-report` |
| Monthly report | `0 2 1 * *` | `run_etl.py --monthly-report` |

### 1.2 Check ETL Status

```bash
cd ~/LifeData && venv/bin/python run_etl.py --status
```

This reads the last 7 entries from `metrics.jsonl` and prints:
- Run history table (date, duration, events ingested, failed modules, DB size, disk free)
- Per-module breakdown from the latest run
- Warnings: module failures, DB size > 5 GB, disk free < 20 GB, event count drops > 50%

### 1.3 Trace an Event

To trace the full provenance of a single event:

```bash
cd ~/LifeData && venv/bin/python run_etl.py --trace <raw_source_id>
```

Prefix matching is supported -- you do not need the full SHA-256 hash. Output includes:
- Full event record (all columns)
- Inferred source file in `raw/`
- Parser version
- Related daily summaries for that date and module
- Related correlations

### 1.4 Log Files

| File | Contents |
|------|----------|
| `~/LifeData/logs/etl.log` | Human-readable ETL log |
| `~/LifeData/logs/etl.jsonl` | Structured JSON-lines log |
| `~/LifeData/metrics.jsonl` | Per-run structured metrics |

**Rotation:** Log files older than `retention.log_rotation_days` (default: 30 days) are automatically deleted at the start of each ETL run. The orchestrator calls `enforce_log_rotation()` on startup.

To check current log size:

```bash
du -sh ~/LifeData/logs/
```

---

## 2. Backup & Recovery

### 2.1 How Backups Work

Before any writes, the ETL creates a backup using SQLite's `conn.backup()` API. This produces a consistent snapshot even during WAL checkpointing -- it is not a file copy.

- Backup runs once per calendar day (skips if today's backup already exists).
- Location: `~/LifeData/db/backups/lifedata.db.bak.YYYY-MM-DD`
- Retention: controlled by `retention.db_backup_keep_days` (default: 7 days). Older backups are pruned automatically.
- Permissions: backup files are chmod 0600, backup directory is chmod 0700.

### 2.2 Restore from Backup

```bash
# 1. Stop any running ETL
cd ~/LifeData

# 2. List available backups
ls -la db/backups/

# 3. Move the current (possibly corrupt) database aside
mv db/lifedata.db db/lifedata.db.broken
mv db/lifedata.db-wal db/lifedata.db-wal.broken 2>/dev/null
mv db/lifedata.db-shm db/lifedata.db-shm.broken 2>/dev/null

# 4. Copy the backup into place
cp db/backups/lifedata.db.bak.2026-03-25 db/lifedata.db
chmod 600 db/lifedata.db

# 5. Run ETL to re-ingest any data generated since the backup
venv/bin/python run_etl.py --report
```

Since ingestion is idempotent (deterministic `event_id` via SHA-256 with `INSERT OR REPLACE`), re-running the ETL after restoring a backup is safe and will fill in any missing events.

### 2.3 Full Rebuild from Raw Data

If all backups are corrupted or unavailable, the database can be rebuilt from scratch because raw data files are never modified:

```bash
# 1. Remove the corrupt database
rm db/lifedata.db db/lifedata.db-wal db/lifedata.db-shm 2>/dev/null

# 2. Run ETL -- schema is created automatically, all raw files are re-parsed
venv/bin/python run_etl.py --report
```

This will:
- Create a fresh database with all tables and indexes
- Re-parse every file under `raw/`
- Recompute all derived metrics via `post_ingest()`
- Generate a daily report

**Caveat:** API-fetched data in `raw/api/` is only as complete as what was previously fetched. If those files were lost, historical API data cannot be recovered.

---

## 3. Database Maintenance

### 3.1 VACUUM

VACUUM rebuilds the database file, reclaiming space from deleted rows and defragmenting pages. Run it when the database has grown significantly after bulk deletions:

```bash
cd ~/LifeData
sqlite3 db/lifedata.db "VACUUM;"
```

**When to use:** After deleting large amounts of data, or quarterly as preventive maintenance. VACUUM requires roughly 2x the database size in free disk space and takes an exclusive lock (no concurrent reads).

### 3.2 ANALYZE

Refresh query planner statistics so SQLite chooses optimal indexes:

```bash
sqlite3 db/lifedata.db "ANALYZE;"
```

Run after significant data growth (e.g., monthly).

### 3.3 FTS5 Rebuild

If full-text search returns stale or missing results, rebuild the FTS index:

```bash
sqlite3 db/lifedata.db "INSERT INTO events_fts(events_fts) VALUES('rebuild');"
```

This re-indexes all rows from the `events` content table into the FTS5 index.

### 3.4 Schema Migration Verification

Check which migrations have been applied:

```bash
sqlite3 db/lifedata.db "SELECT module_id, version, applied_at, sql_hash FROM schema_versions ORDER BY module_id, version;"
```

Migrations are append-only and versioned by list index. The framework in `Database.apply_migrations()` tracks each applied migration in the `schema_versions` table and never re-applies an already-applied version.

### 3.5 Integrity Check

```bash
sqlite3 db/lifedata.db "PRAGMA integrity_check;"
```

Expected output: `ok`. Any other output indicates corruption -- restore from backup (section 2.2) or rebuild (section 2.3).

### 3.6 WAL Checkpoint

The orchestrator runs `PRAGMA wal_checkpoint(TRUNCATE)` automatically after every ETL run, which resets the WAL file to zero length. To run manually:

```bash
sqlite3 db/lifedata.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

Use this if the WAL file (`lifedata.db-wal`) grows unexpectedly large between ETL runs.

---

## 4. Key Rotation

### 4.1 PII_HMAC_KEY Rotation

The social module uses `PII_HMAC_KEY` to hash contact identifiers. Rotating this key changes all hashed identifiers, breaking continuity with historical data. Procedure:

```bash
# 1. Generate a new key
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Back up the current database (the old hashes will no longer be reproducible)
cd ~/LifeData
sqlite3 db/lifedata.db ".backup db/backups/lifedata.db.pre-key-rotation"

# 3. Update the key in .env
#    Edit ~/LifeData/.env and replace the PII_HMAC_KEY value

# 4. Delete social module events so they are re-hashed on next run
sqlite3 db/lifedata.db "DELETE FROM events WHERE source_module LIKE 'social.%';"
sqlite3 db/lifedata.db "DELETE FROM daily_summaries WHERE source_module LIKE 'social.%';"

# 5. Run ETL to re-ingest with new hashes
venv/bin/python run_etl.py

# 6. VACUUM to reclaim space from deleted rows
sqlite3 db/lifedata.db "VACUUM;"
```

**Important:** After rotation, the old key cannot reproduce the same hashes. Correlations and reports that reference old social hashed identifiers will not match new ones. This is a breaking change by design.

### 4.2 API Key Rotation

API keys are stored in `~/LifeData/.env` and referenced in `config.yaml` as `${ENV_VAR}` placeholders. To rotate:

```bash
# 1. Edit ~/LifeData/.env with the new key value
# 2. Verify permissions
chmod 600 ~/LifeData/.env
# 3. Test with a dry run
cd ~/LifeData && venv/bin/python run_etl.py --dry-run
```

No data migration is needed for API key rotation -- the new key is used for all future fetches.

---

## 5. Common Failure Scenarios

### 5.1 Stale Lock File

**Symptom:** `ETL already running (lockfile held). Exiting.`

The lock uses `flock()` on `~/LifeData/.etl.lock`, which is automatically released when the process exits (even on crash). A stale message means either:
- Another ETL process is genuinely still running -- check with `ps aux | grep run_etl`
- The filesystem has a stale NFS lock (unlikely on local disk)

```bash
# Check if a process actually holds the lock
fuser ~/LifeData/.etl.lock

# If no process is listed, the lock is stale. Since flock is fd-based,
# simply re-running the ETL will acquire the lock normally.
# If a zombie process holds it:
kill <pid>
```

### 5.2 Syncthing Partial Sync

**Symptom:** Truncated rows, parse errors, or fewer events than expected.

The ETL skips files modified within the last `file_stability_seconds` (default: 60s). If a large file is still syncing when the ETL runs:
- The file is deferred to the next run (logged as "Skipping unstable file").
- No manual action needed -- the next nightly run will pick it up.

To verify sync completion:

```bash
# Check for recently modified files
find ~/LifeData/raw/ -mmin -5 -type f
```

If Syncthing is stuck, check its web UI (typically `http://localhost:8384`).

### 5.3 Module Fails Mid-ETL

**Symptom:** Exit code 1, "MODULE FAILED" in logs, but other modules succeeded.

Each module runs in its own SAVEPOINT. A failure in one module rolls back only that module's writes -- all other modules are unaffected. The failed module is recorded in `modules` table with `last_status = 'failed'`.

```bash
# Check which module failed and why
venv/bin/python run_etl.py --status

# Re-run just the failed module
venv/bin/python run_etl.py --module <module_name>

# Check detailed error in logs
tail -50 ~/LifeData/logs/etl.log
```

### 5.4 Disk Full

**Symptom:** `sqlite3.OperationalError: disk I/O error` or `OSError: [Errno 28] No space left on device`

```bash
# 1. Check disk usage
df -h ~/LifeData
du -sh ~/LifeData/db/ ~/LifeData/logs/ ~/LifeData/raw/ ~/LifeData/reports/

# 2. Prune old logs manually if rotation hasn't run
find ~/LifeData/logs/ -name "*.log" -mtime +7 -delete
find ~/LifeData/logs/ -name "*.jsonl" -mtime +7 -delete

# 3. Remove old reports
find ~/LifeData/reports/ -name "*.md" -mtime +90 -delete

# 4. VACUUM the database to reclaim space
sqlite3 ~/LifeData/db/lifedata.db "VACUUM;"

# 5. Re-run ETL
cd ~/LifeData && venv/bin/python run_etl.py --report
```

The `--status` command warns when disk free falls below 20 GB.

### 5.5 Database Corruption

**Symptom:** `sqlite3.DatabaseError: database disk image is malformed`

```bash
# 1. Confirm corruption
sqlite3 ~/LifeData/db/lifedata.db "PRAGMA integrity_check;"

# 2. Attempt to salvage what you can
sqlite3 ~/LifeData/db/lifedata.db ".recover" | sqlite3 ~/LifeData/db/lifedata.recovered.db

# 3. If .recover works, replace the database
mv ~/LifeData/db/lifedata.db ~/LifeData/db/lifedata.db.corrupt
mv ~/LifeData/db/lifedata.recovered.db ~/LifeData/db/lifedata.db

# 4. If .recover fails, restore from backup (section 2.2) or rebuild (section 2.3)
```

---

## 6. Monitoring Checklist

### Weekly

- [ ] Run `python run_etl.py --status` and review warnings
- [ ] Confirm no module failures in the last 7 runs
- [ ] Spot-check the latest daily report in `~/LifeData/reports/`
- [ ] Verify Syncthing is connected and syncing (web UI or `syncthing cli show connections`)

### Monthly

- [ ] Run `sqlite3 db/lifedata.db "ANALYZE;"` to refresh query planner statistics
- [ ] Check database size: `du -sh ~/LifeData/db/lifedata.db`
- [ ] Check disk free: `df -h ~/LifeData`
- [ ] Review `metrics.jsonl` for duration trends (ETL getting slower?)
- [ ] Verify backups exist: `ls -la ~/LifeData/db/backups/`
- [ ] Review weekly report for correlation and anomaly changes

### Quarterly

- [ ] Run `sqlite3 db/lifedata.db "PRAGMA integrity_check;"`
- [ ] Run `sqlite3 db/lifedata.db "VACUUM;"` if database has grown significantly
- [ ] Rebuild FTS index: `sqlite3 db/lifedata.db "INSERT INTO events_fts(events_fts) VALUES('rebuild');"`
- [ ] Review `.env` API keys -- rotate any that are older than 90 days
- [ ] Check file permissions: `.env` is 0600, `~/LifeData/` is 0700
- [ ] Verify schema migrations: `sqlite3 db/lifedata.db "SELECT * FROM schema_versions;"`

### Annual

- [ ] Rotate `PII_HMAC_KEY` (section 4.1) if required by your data policy
- [ ] Archive old raw data beyond `retention.raw_files_days` (365 days default)
- [ ] Review `config.yaml` for stale settings, disabled modules, or unused patterns
- [ ] Test a full rebuild from raw data on a separate machine to verify data integrity
- [ ] Update Python dependencies: `pip install --upgrade -r requirements.txt` and run `make test`
