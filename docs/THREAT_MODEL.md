# LifeData V4 — Threat Model

Last reviewed: 2026-03-25

This document describes what LifeData protects, who it protects against,
and how the current architecture addresses (or fails to address) each
attack vector.

---

## Assets (what are we protecting?)

| Asset | Location | Sensitivity |
|-------|----------|-------------|
| **Location history** | `events.location_lat/lon`, raw geofence/hourly CSVs | High — enables physical tracking, home/work inference |
| **Behavioral patterns** | Screen time, app usage, unlock cadence, sleep schedule | High — reveals daily habits, routines, absences |
| **Communication metadata** | Call/SMS logs (HMAC-hashed contacts/phones), notification text | High — even hashed metadata reveals social graph shape |
| **Health data** | Mood, energy, stress, caffeine, sleep quality, pain | High — medical/insurance implications |
| **Voice recordings & transcripts** | `raw/LifeData/logs/media/`, `events.value_text` (truncated to 2000 chars) | Critical — contains spoken words, dreams, personal thoughts |
| **API keys** | `.env` (chmod 600) | Medium — abuse costs money, enables impersonation of fetch requests |
| **The aggregate** | The full SQLite database + raw/ tree | **Critical** — a complete behavioral model of one person over time |

### Why "the aggregate" is the primary asset

Individual data points are low-value. The combination — knowing someone
was at coordinates X at 3 AM, slept poorly, had elevated stress, and
received 12 notifications from the same app — constructs a behavioral
fingerprint that no single data source reveals alone.

---

## Trust Boundaries

```
┌──────────────┐     Syncthing (LAN only)     ┌───────────────────┐
│  Phone       │ ───────────────────────────── │  Desktop          │
│  (Tasker)    │   encrypted, no relays        │  (ETL + DB)       │
└──────────────┘                               └─────┬─────────────┘
                                                     │
                                               ┌─────┴─────────────┐
                                               │  External APIs    │
                                               │  (weather, news,  │
                                               │   GDELT, markets) │
                                               └───────────────────┘
```

| Boundary | Trust level | Notes |
|----------|-------------|-------|
| **Phone (Tasker + Syncthing)** | High — we control it | Physical possession required; Tasker tasks write CSVs |
| **Network (local WiFi)** | Medium | Syncthing encrypts in transit; but WiFi itself may be shared |
| **Desktop (ETL, DB, analysis)** | High — we control it | Single-user Linux machine; LUKS full-disk encryption expected |
| **External APIs** | Low | We send our IP + API keys; they return public data; no PII sent |
| **Report files** | Medium | Markdown/HTML in `reports/` — could be opened by other tools or shared |

---

## Threat Actors

| Actor | Capability | Motivation |
|-------|-----------|------------|
| **Opportunistic local access** | Physical access to unlocked machine (roommate, repair shop) | Curiosity, leverage |
| **Desktop malware** | Full user-level access to filesystem | Data exfiltration, credential theft |
| **Phone malware** | Access to Tasker data, Syncthing config | Same as above, from the phone side |
| **Syncthing compromise** | MITM if relays enabled; config manipulation | Intercept raw data in transit |
| **Stolen device** | Full disk access (mitigated by FDE) | Long-term data extraction |
| **Cloud backup leak** | If raw/ or db/ accidentally backed up to cloud | Mass exposure |

---

## Attack Vectors & Mitigations

### 1. Syncthing relay data exposure

**Attack:** If Syncthing relays are enabled, raw CSV data (containing GPS,
contacts, health data) transits through third-party relay servers. Relay
operators could log traffic.

**Current mitigation:**
- `config.yaml`: `syncthing_relay_enabled: false` (enforced)
- `config_schema.py`: validator rejects `syncthing_relay_enabled: true` at startup
- META module: `verify_syncthing_relay()` checks the Syncthing API every ETL run and flags relay usage as `critical` severity

**Residual risk:** If Syncthing is reconfigured outside of LifeData (e.g.,
via the Syncthing web UI), the META check only catches it at the next ETL
run, not in real time.

**TODO:** Consider a systemd timer that checks relay status independently
of the ETL schedule.

---

### 2. .env file exposure

**Attack:** API keys in `.env` are stolen via filesystem access, backup
leak, or accidental git commit.

**Current mitigation:**
- `.env` is in `.gitignore` (line 16–17)
- `.env` is NOT in any Syncthing-synced directory
- `config.py` loads `.env` with `override=False` (won't clobber existing env vars)
- Startup security check verifies `.env` permissions are 0600

**Residual risk:** If the user stores `.env` in a cloud-synced directory or
makes a one-off copy, the permission check won't catch it.

---

### 3. Database theft

**Attack:** The SQLite database (`db/lifedata.db`) contains the complete
behavioral model. A stolen or copied database exposes everything.

**Current mitigation:**
- Full-disk encryption (LUKS/fscrypt) is the primary defense
- Database file permissions are 0600 (set by `Database.__init__`)
- Database directory permissions are 0700
- Startup security check verifies LUKS/fscrypt is active (best-effort)
- `.gitignore` excludes `db/`

**Residual risk:** LUKS protects at rest only; if the machine is running and
unlocked, the database is accessible to any process running as the user.
SQLite does not support native encryption (would need SQLCipher or
application-level encryption).

**TODO:** Evaluate SQLCipher for at-rest DB encryption independent of FDE.

---

### 4. CSV injection

**Attack:** A malformed CSV in `raw/` contains spreadsheet formulas
(e.g., `=SYSTEM("curl ...")`) that execute if the file is opened in
LibreOffice or Excel.

**Current mitigation:**
- The ETL reads CSVs with Python's `str.split(",")` and `csv.DictReader` — neither interprets formulas
- `safe_parse_rows()` treats every field as a string — no formula evaluation

**Residual risk:** If a user opens a raw CSV directly in LibreOffice Calc,
formulas could execute. LibreOffice macro settings may not be restrictive.

**IMPORTANT: Never open raw CSVs in spreadsheet software directly.**
Use `python -c "import csv; ..."` or `less` for manual inspection.

---

### 5. Path traversal via malformed filenames

**Attack:** A Syncthing-synced filename like `../../../etc/passwd` or a
symlink could trick the ETL into reading files outside `raw/`.

**Current mitigation:**
- `Orchestrator._is_safe_path()`: resolves symlinks via `Path.resolve()`,
  then checks `is_relative_to(raw_base)` — blocks all traversal
- `modules/media/parsers.py`: `_safe_media_path()` does the same check for
  media files, plus `_is_safe_media_id()` rejects filenames with
  non-alphanumeric characters
- Extension whitelist: only `.csv` and `.json` files are parsed
- `ALLOWED_EXTENSIONS = {".csv", ".json"}` in orchestrator

**Residual risk:** Low. The `Path.resolve()` + `is_relative_to()` pattern
is robust against known traversal techniques including symlinks,
double-encoding, and null bytes.

---

### 6. Log injection

**Attack:** Malformed CSV data containing newlines or JSON metacharacters
could corrupt the structured log file, potentially injecting fake log
entries that mislead forensic analysis.

**Current mitigation:**
- `core/logger.py`: `StructuredFormatter` strips all `\r\n` from messages
  via `_NEWLINE_RE.sub(" ", ...)` before JSON serialization
- Log file is JSON-lines format — each entry is `json.dumps()`, which
  escapes special characters
- `core/sanitizer.py`: `sanitize_for_log()` applied to raw CSV data
  before logging, redacting PII patterns

**Residual risk:** Very low. The combination of newline stripping and JSON
encoding prevents injection.

---

### 7. API key leakage in logs

**Attack:** API keys appear in log output, then persist in `logs/etl.log`
or are visible on screen during ETL runs.

**Current mitigation:**
- **Audit result (2026-03-24):** No log statement in the codebase directly
  logs API key values. Keys are passed in-memory only.
- `config_schema.py`: when warning about missing keys, logs the *field name*
  and the *placeholder* (e.g., `"${WEATHER_API_KEY}"`), not the resolved value.
  If the key IS resolved, the warning is not triggered at all.
- `core/sanitizer.py`: `sanitize_for_log()` redacts strings matching common
  API key patterns (32+ hex chars, Bearer tokens, etc.)
- Log file permissions are 0600
- Scripts (`fetch_news.py`, `fetch_markets.py`) pass keys via `params=`
  to `requests.get()` — they are URL-encoded in the request but never logged

**Residual risk:** A future code change could accidentally log a key. The
sanitizer provides defense-in-depth.

---

### 8. Contact name exposure

**Attack:** Raw contact names or phone numbers appear in the database or
logs, enabling identification of the user's social connections.

**Current mitigation:**
- `modules/social/parsers.py`: all contact names and phone numbers are
  hashed via HMAC-SHA256 with a per-installation key (`PII_HMAC_KEY`
  env var, defaults to `lifedata-pii-{hostname}`)
- HMAC output is truncated to 16 hex chars (64 bits) — sufficient to prevent
  rainbow tables given the small input space
- Hashing happens at parse time, before events are created — raw names
  never enter the Event pipeline
- Notification text is truncated to 500 chars

**Residual risk:**
- If `PII_HMAC_KEY` is compromised AND the attacker has the contact list,
  they can re-hash and correlate. The key is per-installation, not global.
- The default key derivation (`lifedata-pii-{hostname}`) is deterministic —
  if the hostname is known, the key is known. Users should set a custom
  `PII_HMAC_KEY` in `.env`.

**TODO:** Document `PII_HMAC_KEY` rotation procedure and make the default
key derivation include a random salt generated at first run.

---

### 9. GPS coordinate precision in logs

**Attack:** Full-precision GPS coordinates (6+ decimal places, ~10cm accuracy)
appear in log output, enabling precise location tracking from log files alone.

**Current mitigation:**
- `core/sanitizer.py`: `sanitize_for_log()` detects coordinate-like patterns
  and truncates to 2 decimal places (~1.1km precision) in log output
- GPS coordinates in the *database* retain full precision (needed for
  location diversity and geofencing accuracy)
- Log files are chmod 0600

**Residual risk:** The database itself contains full-precision coordinates.
This is by design (analytics need accuracy), but means database theft
exposes precise location history. FDE is the primary defense.

---

### 10. Voice transcript exposure

**Attack:** Raw voice transcripts stored in the database or logged during
parsing could expose deeply personal content (dreams, thoughts, dictation).

**Current mitigation:**
- Transcripts stored in `events.value_text`, truncated to 2000 characters
- `core/sanitizer.py`: redacts transcript-like content from log messages
- Whisper transcription is gated by `auto_transcribe` config flag (opt-in)
- Media files themselves are in `media/` (chmod 700 directory, .gitignore'd)

**Residual risk:** Transcripts in the database are plaintext. FDE protects
at rest, but any process running as the user can read them.

**TODO:** Evaluate application-level encryption for transcript fields.

---

## Operational Security Checklist

- [ ] LUKS full-disk encryption enabled on desktop
- [ ] `.env` file permissions are 0600
- [ ] `config.yaml` permissions are 0600 or 0644
- [ ] `~/LifeData/` directory permissions are 0700
- [ ] Syncthing relays disabled (META module verifies)
- [ ] `PII_HMAC_KEY` set to a custom value in `.env`
- [ ] No raw CSVs opened in spreadsheet software
- [ ] `~/LifeData/` is NOT inside a cloud-sync directory (Dropbox, Google Drive, etc.)
- [ ] `~/LifeData/` is NOT inside a Syncthing shared folder
- [ ] Backups of `db/` are encrypted before leaving the machine

---

## Startup Security Checks

The `Orchestrator.__init__()` runs automated checks at every ETL startup:

1. **`.env` permissions** — warns if not 0600
2. **`config.yaml` permissions** — warns if not 0600 or 0644
3. **`~/LifeData/` directory permissions** — warns if not 0700
4. **Syncthing shared folder** — warns if `~/LifeData/` contains `.stfolder/` marker
5. **Disk encryption** — best-effort check for LUKS/fscrypt on the partition

---

## Security Audit Remediation History

**Audit date:** 2026-03-24
**Auditor:** Claude Code (Security Engineering Review)
**Status:** All 21 findings remediated and verified.

| ID | Severity | Finding | Remediation |
|----|----------|---------|-------------|
| H-1 | High | Empty allowlist bypassed module security (fail-open) | Changed to fail-closed: empty allowlist = 0 modules loaded |
| H-2 | High | Unrestricted SQL via `execute()` in schema migrations | New `execute_migration()` validates CREATE/ALTER only; `execute()` restricted to SELECT |
| H-3 | High | `post_ingest()` receives full Database object | Mitigated by H-1 (only trusted modules get access); documented as accepted risk |
| M-1 | Medium | Database file created with default permissions | `chmod 0o600` on db file, `0o700` on db directory at creation |
| M-2 | Medium | Backup files created with default permissions | `chmod 0o600` on backup files, `0o700` on backup directory |
| M-3 | Medium | Log files created with default permissions | `chmod 0o600` on `etl.log` after creation |
| M-4 | Medium | No file extension whitelist on parsed files | Added `ALLOWED_EXTENSIONS = {".csv", ".json"}` filter |
| M-5 | Medium | Pydantic config schema had no Syncthing relay validator | Added hard-error validator rejecting `syncthing_relay_enabled: true` |
| M-6 | Medium | Config schema had no module allowlist validator | Added `allowlist_not_empty` validator requiring >= 1 module |
| M-7 | Medium | No startup permission checks | Added 5-point startup security check (env, config, dir, stfolder, encryption) |
| M-8 | Medium | Config schema had no timezone validator | Added `zoneinfo.ZoneInfo` validation for timezone field |
| L-1 | Low | Log messages could contain raw CSV data with PII | Added `sanitizer.py` with coordinate truncation, phone/email/key redaction |
| L-2 | Low | Newline injection possible in structured logs | Added `_NEWLINE_RE` stripping in `StructuredFormatter` |
| L-3 | Low | No file stability window for mid-sync files | Added `file_stability_seconds` (60s) — skip files modified recently |
| L-4 | Low | No ETL concurrency protection | Added `flock`-based exclusive lock with timeout |
| L-5 | Low | Database backup used `shutil.copy2` | Replaced with SQLite `conn.backup()` API for safe online backups |
| L-6 | Low | No FTS5 delete trigger for INSERT OR REPLACE | Added `AFTER DELETE` trigger to clean stale FTS entries |
| L-7 | Low | `post_ingest()` recomputed all historical dates | Added `affected_dates` parameter; modules only recompute changed dates |
| L-8 | Low | No expression index for date-based queries | Added `CREATE INDEX idx_events_date_local ON events(date(timestamp_local))` |
| L-9 | Low | No rate limiting on API fetcher scripts | Added `scripts/_http.retry_get()` with exponential backoff |
| D-1 | Design | Module sovereignty violation: analysis layer queries hardcoded source_module strings | Documented; modules should register metrics via `get_daily_summary()` (future work) |

For original code snapshots and detailed revert instructions, see git history at commit `6d78a42` (pre-audit baseline).
