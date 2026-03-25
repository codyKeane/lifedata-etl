"""
LifeData V4 — Orchestrator
core/orchestrator.py

Main ETL execution engine. Loads configuration, discovers modules,
validates file paths, and runs each module's parse → insert pipeline
with SAVEPOINT isolation.
"""

import importlib
import json
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from core.config import load_config
from core.config_schema import ConfigValidationError, RootConfig
from core.database import Database
from core.logger import get_logger, setup_logging
from core.metrics import ETLMetrics, ModuleMetrics, write_metrics
from core.module_interface import ModuleInterface

log = get_logger("lifedata.orchestrator")

# Allowed file extensions for module parsing
ALLOWED_EXTENSIONS = {".csv", ".json"}


class Orchestrator:
    """Main ETL execution engine."""

    def __init__(self, config_path: str = "~/LifeData/config.yaml"):
        # Load, resolve env vars, and validate config in one step
        try:
            self.config: RootConfig = load_config(config_path)
            log.info("Config validation passed")
        except ConfigValidationError as e:
            log.error(str(e))
            raise

        # Set up structured logging now that we have the config
        setup_logging(self.config.lifedata.log_path)

        # Security hardening checks (warnings only — never block ETL)
        self._check_startup_security(config_path)

        self.db = Database(self.config.lifedata.db_path)
        self.modules: list[ModuleInterface] = []

    def _check_startup_security(self, config_path: str) -> list[str]:
        """Run security posture checks at startup. Returns list of warnings.

        These are advisory — they log warnings but never prevent the ETL
        from running. The threat model documents why each check matters.
        """
        warnings: list[str] = []

        # 1. .env file permissions should be 0600
        env_path = os.path.expanduser("~/LifeData/.env")
        if os.path.exists(env_path):
            mode = os.stat(env_path).st_mode & 0o777
            if mode != 0o600:
                msg = f".env permissions are {oct(mode)} (should be 0o600)"
                warnings.append(msg)
                log.warning(f"SECURITY: {msg}")

        # 2. config.yaml permissions should be 0600 or 0644
        cfg_expanded = os.path.expanduser(config_path)
        if os.path.exists(cfg_expanded):
            mode = os.stat(cfg_expanded).st_mode & 0o777
            if mode not in (0o600, 0o644):
                msg = f"config.yaml permissions are {oct(mode)} (should be 0o600 or 0o644)"
                warnings.append(msg)
                log.warning(f"SECURITY: {msg}")

        # 3. ~/LifeData/ directory permissions should be 0700
        lifedata_dir = os.path.expanduser("~/LifeData")
        if os.path.isdir(lifedata_dir):
            mode = os.stat(lifedata_dir).st_mode & 0o777
            if mode != 0o700:
                msg = f"~/LifeData/ permissions are {oct(mode)} (should be 0o700)"
                warnings.append(msg)
                log.warning(f"SECURITY: {msg}")

        # 4. ~/LifeData/ should NOT be inside a Syncthing shared folder
        # Syncthing creates a .stfolder/ marker in shared directories
        stfolder = os.path.join(lifedata_dir, ".stfolder")
        if os.path.exists(stfolder):
            msg = (
                "~/LifeData/ contains .stfolder/ — it appears to be a "
                "Syncthing shared folder. The database and logs should NOT "
                "be synced. Only raw/ should be synced."
            )
            warnings.append(msg)
            log.warning(f"SECURITY: {msg}")

        # 5. Best-effort LUKS/fscrypt check on the partition
        try:
            self._check_disk_encryption(lifedata_dir, warnings)
        except Exception:
            pass  # best-effort — never fail on this

        if not warnings:
            log.info("Startup security checks passed")

        return warnings

    @staticmethod
    def _check_disk_encryption(path: str, warnings: list[str]) -> None:
        """Best-effort check for LUKS or fscrypt on the partition holding path."""
        try:
            # Find the mount point device for the path
            result = subprocess.run(
                ["df", "--output=source", path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return
            lines = result.stdout.strip().splitlines()
            if len(lines) < 2:
                return
            device = lines[1].strip()

            # Check if the device is a LUKS-mapped dm-crypt volume
            # dm-crypt devices show up as /dev/dm-* or /dev/mapper/*
            if "/dev/mapper/" in device or "/dev/dm-" in device:
                log.info(f"Disk encryption: {device} appears to be a dm-crypt/LUKS volume")
                return

            # Check fscrypt policy on the directory
            result = subprocess.run(
                ["fscryptctl", "get_policy", path],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                log.info(f"Disk encryption: fscrypt policy active on {path}")
                return

            # Neither detected
            msg = (
                f"No disk encryption detected on {device}. "
                "LUKS full-disk encryption is strongly recommended."
            )
            warnings.append(msg)
            log.warning(f"SECURITY: {msg}")
        except FileNotFoundError:
            # df or fscryptctl not available — skip silently
            pass

    @staticmethod
    def _is_safe_path(path: str, raw_base: str) -> bool:
        """Validate that a discovered file path does not escape raw_base.

        Prevents path traversal attacks from malformed Syncthing-landed filenames.
        Also accepts paths under the raw/ parent directory (for API-fetched data
        in raw/api/ used by the world module).
        """
        try:
            resolved = Path(path).resolve()
            base = Path(raw_base).resolve()
            if resolved.is_relative_to(base):
                return True
            # Also accept paths under the raw/ root (parent of raw_base)
            # This covers raw/api/ for API-fetched data (world module)
            raw_root = base
            while raw_root.name and raw_root.name != "raw":
                raw_root = raw_root.parent
            if raw_root.name == "raw" and resolved.is_relative_to(raw_root):
                return True
            return False
        except Exception:
            return False

    def discover_modules(self, single_module: str | None = None) -> None:
        """Auto-discover modules, restricted to the module_allowlist in config.

        Args:
            single_module: If set, only load this one module (for --module flag).
        """
        self.modules = []
        allowlist = self.config.lifedata.security.module_allowlist
        modules_dir = Path(__file__).parent.parent / "modules"

        if not modules_dir.exists():
            log.error(f"Modules directory not found: {modules_dir}")
            return

        for module_dir in sorted(modules_dir.iterdir()):
            if not module_dir.is_dir():
                continue
            if not (module_dir / "module.py").exists():
                continue

            module_name = module_dir.name

            # If --module flag is set, skip everything else
            if single_module and module_name != single_module:
                continue

            # SECURITY: only load modules explicitly allowlisted in config
            # Fail-closed: if allowlist is empty or missing, refuse to load
            if not allowlist:
                log.error(
                    "No module allowlist configured in config.yaml — "
                    "refusing to load any modules (fail-closed)"
                )
                return
            if module_name not in allowlist:
                log.warning(f"Module '{module_name}' not in allowlist, skipping")
                continue

            # Check if module is enabled
            mod_cfg_obj = getattr(self.config.lifedata.modules, module_name, None)
            module_config = mod_cfg_obj.model_dump() if mod_cfg_obj else {}
            if not module_config.get("enabled", True):
                log.info(f"Module '{module_name}' is disabled, skipping")
                continue

            # Inject top-level paths into meta module config so it can
            # run storage/sync checks without the full config tree
            if module_name == "meta":
                module_config["_raw_base"] = self.config.lifedata.raw_base
                module_config["_db_path"] = self.config.lifedata.db_path
                module_config["syncthing_api_key"] = (
                    self.config.lifedata.security.syncthing_api_key
                )

            try:
                mod = importlib.import_module(f"modules.{module_name}.module")
                instance = mod.create_module(module_config)

                if not isinstance(instance, ModuleInterface):
                    log.error(
                        f"Module '{module_name}' doesn't implement ModuleInterface"
                    )
                    continue

                self.modules.append(instance)
                log.info(f"Loaded module: {instance.module_id} v{instance.version}")
            except Exception as e:
                log.error(f"Failed to load module '{module_name}': {e}", exc_info=True)

    def run(
        self,
        report: bool = False,
        single_module: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Main ETL execution.

        Args:
            report: Generate daily report after ETL.
            single_module: Only run a specific module.
            dry_run: Parse but don't write to DB.

        Returns:
            Summary dict with counts and status.
        """
        log.info("=" * 60)
        log.info("LifeData ETL V4 — starting")
        log.info("=" * 60)

        # Ensure schema
        self.db.ensure_schema()

        # Backup DB before any writes
        if not dry_run:
            self.db.backup(keep_days=self.config.lifedata.retention.db_backup_keep_days)

        # Reset affected dates tracker
        self.db.reset_affected_dates()

        # Discover and load modules
        self.discover_modules(single_module=single_module)

        if not self.modules:
            log.warning("No modules loaded — nothing to do")
            return {"total_events": 0, "failed_modules": [], "modules_run": 0}

        metrics = ETLMetrics(
            started_utc=datetime.now(timezone.utc).isoformat(),
        )
        run_start = time.time()
        all_quarantined: list[str] = []
        raw_base = os.path.expanduser(self.config.lifedata.raw_base)
        stability_seconds = self.config.lifedata.etl.file_stability_seconds

        for module in self.modules:
            log.info(f"[{module.module_id}] Starting module run")
            mod_start = time.time()
            mm = ModuleMetrics(module_id=module.module_id, status="success")

            try:
                # Schema migrations (DDL only)
                for sql in module.schema_migrations():
                    self.db.execute_migration(sql)

                # Discover files → validate paths → filter extensions
                all_files = module.discover_files(raw_base)
                mm.files_discovered = len(all_files)

                safe_files = []
                now = time.time()
                unstable_count = 0
                for f in all_files:
                    if not self._is_safe_path(f, raw_base):
                        log.warning(
                            f"[{module.module_id}] Path escapes raw_base, skipping: {f}"
                        )
                        continue
                    ext = Path(f).suffix.lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        log.warning(
                            f"[{module.module_id}] Disallowed extension "
                            f"'{ext}', skipping: {f}"
                        )
                        continue
                    # Skip files modified within the stability window
                    # (likely mid-sync by Syncthing — parsing a half-written
                    # file produces corrupt data or truncated rows)
                    try:
                        mtime = os.path.getmtime(f)
                        if (now - mtime) < stability_seconds:
                            log.info(
                                f"[{module.module_id}] Skipping unstable file "
                                f"(modified {now - mtime:.0f}s ago): {f}"
                            )
                            unstable_count += 1
                            continue
                    except OSError:
                        # File disappeared between discover and stat — skip it
                        continue
                    safe_files.append(f)

                mm.files_parsed = len(safe_files)
                rejected = len(all_files) - len(safe_files)
                log.info(
                    f"[{module.module_id}] Found {len(safe_files)} safe files"
                    + (f" ({rejected} rejected)" if rejected else "")
                    + (
                        f" ({unstable_count} deferred — modified within "
                        f"{stability_seconds}s)"
                        if unstable_count
                        else ""
                    )
                )

                # Parse all files
                events = []
                for f in safe_files:
                    try:
                        parsed = module.parse(f)
                        events.extend(parsed)
                    except Exception as e:
                        log.warning(f"[{module.module_id}] Failed to parse {f}: {e}")

                mm.events_parsed = len(events)
                log.info(f"[{module.module_id}] Parsed {len(events)} events")

                # Insert (SAVEPOINT-wrapped per module)
                if dry_run:
                    log.info(
                        f"[{module.module_id}] DRY RUN — "
                        f"{len(events)} events would be inserted"
                    )
                    inserted, skipped = len(events), 0
                else:
                    inserted, skipped = self.db.insert_events_for_module(
                        module.module_id, events
                    )

                mm.events_ingested = inserted
                mm.events_skipped = skipped

                log.info(
                    f"[{module.module_id}] Ingested {inserted} events"
                    + (f" ({skipped} invalid skipped)" if skipped else "")
                )

                # Collect quarantined files from modules that support it
                if hasattr(module, "quarantined_files"):
                    qfiles = module.quarantined_files
                    if qfiles:
                        mm.files_quarantined = len(qfiles)
                        all_quarantined.extend(qfiles)
                        log.warning(
                            f"[{module.module_id}] {len(qfiles)} file(s) quarantined"
                        )

                # Post-ingest hooks (isolated — a hook crash should not
                # undo successfully inserted events)
                if not dry_run:
                    try:
                        module.post_ingest(self.db)
                    except Exception as e:
                        log.error(
                            f"[{module.module_id}] post_ingest() failed: {e}",
                            exc_info=True,
                        )

                self.db.update_module_status(
                    module.module_id,
                    display_name=module.display_name,
                    version=module.version,
                    success=True,
                )

            except Exception as e:
                log.error(f"[{module.module_id}] MODULE FAILED: {e}", exc_info=True)
                error_msg = str(e)[:200]
                mm.status = "failed"
                mm.error = error_msg
                self.db.update_module_status(
                    module.module_id,
                    display_name=module.display_name,
                    version=module.version,
                    success=False,
                    error=error_msg,
                )

            mm.duration_sec = round(time.time() - mod_start, 3)
            metrics.modules[module.module_id] = mm

        # Aggregate totals from per-module metrics
        metrics.duration_sec = round(time.time() - run_start, 2)
        metrics.finished_utc = datetime.now(timezone.utc).isoformat()
        metrics.total_events_parsed = sum(
            m.events_parsed for m in metrics.modules.values()
        )
        metrics.total_events_ingested = sum(
            m.events_ingested for m in metrics.modules.values()
        )
        metrics.total_events_skipped = sum(
            m.events_skipped for m in metrics.modules.values()
        )
        metrics.total_files_discovered = sum(
            m.files_discovered for m in metrics.modules.values()
        )
        metrics.total_files_quarantined = sum(
            m.files_quarantined for m in metrics.modules.values()
        )

        # System stats
        db_path = os.path.expanduser(self.config.lifedata.db_path)
        try:
            metrics.db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        except OSError:
            pass
        try:
            disk = shutil.disk_usage(os.path.expanduser("~/LifeData"))
            metrics.disk_free_gb = round(disk.free / (1024**3), 2)
        except OSError:
            pass

        failed_modules = metrics.failed_modules()
        log.info(
            f"ETL complete: {metrics.total_events_ingested} new events, "
            f"{metrics.total_events_skipped} skipped, "
            f"{len(failed_modules)} failed modules"
        )

        if failed_modules:
            log.warning(f"Failed modules: {', '.join(failed_modules)}")

        # Report generation
        if report and not dry_run:
            try:
                from analysis.reports import generate_daily_report

                generate_daily_report(self.db, self.modules, self.config.model_dump())
                log.info("Daily report generated")
            except ImportError:
                log.info(
                    "Analysis module not yet available — skipping report generation"
                )
            except Exception as e:
                log.error(f"Report generation failed: {e}", exc_info=True)

        # Persist structured metrics
        try:
            write_metrics(metrics)
            log.info("Metrics written to metrics.jsonl")
        except OSError as e:
            log.warning(f"Failed to write metrics: {e}")

        summary = {
            "total_events": metrics.total_events_ingested,
            "total_skipped": metrics.total_events_skipped,
            "failed_modules": failed_modules,
            "modules_run": len(self.modules),
            "affected_dates": sorted(self.db.get_affected_dates()),
            "quarantined_files": all_quarantined,
            "metrics": metrics,
        }

        log.info("=" * 60)
        return summary
