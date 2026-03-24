"""
LifeData V4 — Orchestrator
core/orchestrator.py

Main ETL execution engine. Loads configuration, discovers modules,
validates file paths, and runs each module's parse → insert pipeline
with SAVEPOINT isolation.
"""

import importlib
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

from core.database import Database
from core.logger import get_logger, setup_logging
from core.module_interface import ModuleInterface

log = get_logger("lifedata.orchestrator")

# Allowed file extensions for module parsing
ALLOWED_EXTENSIONS = {".csv", ".json"}

# Regex to resolve ${ENV_VAR} placeholders in config values
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


class Orchestrator:
    """Main ETL execution engine."""

    def __init__(self, config_path: str = "~/LifeData/config.yaml"):
        # Load .env first — must be 600, never in Syncthing folder
        env_path = os.path.expanduser("~/LifeData/.env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
        else:
            log.warning(
                ".env file not found at ~/LifeData/.env — API keys may be missing"
            )

        self.config = self._load_config(config_path)

        # Set up structured logging now that we have the config
        log_path = self.config["lifedata"].get(
            "log_path", "~/LifeData/logs/etl.log"
        )
        setup_logging(log_path)

        self.db = Database(self.config["lifedata"]["db_path"])
        self.modules: list[ModuleInterface] = []

    @staticmethod
    def _load_config(path: str) -> dict:
        """Load and resolve config.yaml, substituting ${ENV_VAR} references."""
        expanded = os.path.expanduser(path)
        with open(expanded, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        Orchestrator._resolve_env_vars(config)
        return config

    @staticmethod
    def _resolve_env_vars(obj):
        """Recursively resolve ${ENV_VAR} patterns in config values."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str) and "${" in value:
                    obj[key] = _ENV_VAR_RE.sub(
                        lambda m: os.environ.get(m.group(1), ""), value
                    )
                elif isinstance(value, (dict, list)):
                    Orchestrator._resolve_env_vars(value)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str) and "${" in item:
                    obj[i] = _ENV_VAR_RE.sub(
                        lambda m: os.environ.get(m.group(1), ""), item
                    )
                elif isinstance(item, (dict, list)):
                    Orchestrator._resolve_env_vars(item)

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
        allowlist = (
            self.config["lifedata"]
            .get("security", {})
            .get("module_allowlist", [])
        )
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
            if allowlist and module_name not in allowlist:
                log.warning(f"Module '{module_name}' not in allowlist, skipping")
                continue

            # Check if module is enabled
            module_config = (
                self.config["lifedata"]["modules"].get(module_name, {})
            )
            if not module_config.get("enabled", True):
                log.info(f"Module '{module_name}' is disabled, skipping")
                continue

            # Inject top-level paths into meta module config so it can
            # run storage/sync checks without the full config tree
            if module_name == "meta":
                module_config = dict(module_config)  # shallow copy
                module_config["_raw_base"] = self.config["lifedata"].get(
                    "raw_base", "~/LifeData/raw/LifeData"
                )
                module_config["_db_path"] = self.config["lifedata"].get(
                    "db_path", "~/LifeData/db/lifedata.db"
                )
                # Pass the resolved Syncthing API key
                security = self.config["lifedata"].get("security", {})
                module_config["syncthing_api_key"] = security.get(
                    "syncthing_api_key", ""
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
                log.info(
                    f"Loaded module: {instance.module_id} v{instance.version}"
                )
            except Exception as e:
                log.error(
                    f"Failed to load module '{module_name}': {e}", exc_info=True
                )

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
        retention = self.config["lifedata"].get("retention", {})
        if not dry_run:
            self.db.backup(keep_days=retention.get("db_backup_keep_days", 7))

        # Reset affected dates tracker
        self.db.reset_affected_dates()

        # Discover and load modules
        self.discover_modules(single_module=single_module)

        if not self.modules:
            log.warning("No modules loaded — nothing to do")
            return {"total_events": 0, "failed_modules": [], "modules_run": 0}

        total_events = 0
        total_skipped = 0
        failed_modules: list[str] = []
        raw_base = os.path.expanduser(
            self.config["lifedata"]["raw_base"]
        )

        for module in self.modules:
            log.info(f"[{module.module_id}] Starting module run")

            try:
                # Schema migrations
                for sql in module.schema_migrations():
                    self.db.execute(sql)

                # Discover files → validate paths → filter extensions
                all_files = module.discover_files(raw_base)

                safe_files = []
                for f in all_files:
                    if not self._is_safe_path(f, raw_base):
                        log.warning(
                            f"[{module.module_id}] Path escapes raw_base, "
                            f"skipping: {f}"
                        )
                        continue
                    ext = Path(f).suffix.lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        log.warning(
                            f"[{module.module_id}] Disallowed extension "
                            f"'{ext}', skipping: {f}"
                        )
                        continue
                    safe_files.append(f)

                rejected = len(all_files) - len(safe_files)
                log.info(
                    f"[{module.module_id}] Found {len(safe_files)} safe files"
                    + (f" ({rejected} rejected)" if rejected else "")
                )

                # Parse all files
                events = []
                for f in safe_files:
                    try:
                        parsed = module.parse(f)
                        events.extend(parsed)
                    except Exception as e:
                        log.warning(
                            f"[{module.module_id}] Failed to parse {f}: {e}"
                        )

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

                total_events += inserted
                total_skipped += skipped

                log.info(
                    f"[{module.module_id}] Ingested {inserted} events"
                    + (f" ({skipped} invalid skipped)" if skipped else "")
                )

                # Post-ingest hooks
                if not dry_run:
                    module.post_ingest(self.db)

                self.db.update_module_status(
                    module.module_id,
                    display_name=module.display_name,
                    version=module.version,
                    success=True,
                )

            except Exception as e:
                log.error(
                    f"[{module.module_id}] MODULE FAILED: {e}", exc_info=True
                )
                failed_modules.append(module.module_id)
                self.db.update_module_status(
                    module.module_id,
                    display_name=module.display_name,
                    version=module.version,
                    success=False,
                    error=str(e),
                )

        log.info(
            f"ETL complete: {total_events} new events, "
            f"{total_skipped} skipped, "
            f"{len(failed_modules)} failed modules"
        )

        if failed_modules:
            log.warning(f"Failed modules: {', '.join(failed_modules)}")

        # Report generation
        if report and not dry_run:
            try:
                from analysis.reports import generate_daily_report

                generate_daily_report(self.db, self.modules, self.config)
                log.info("Daily report generated")
            except ImportError:
                log.info(
                    "Analysis module not yet available — skipping report generation"
                )
            except Exception as e:
                log.error(f"Report generation failed: {e}", exc_info=True)

        summary = {
            "total_events": total_events,
            "total_skipped": total_skipped,
            "failed_modules": failed_modules,
            "modules_run": len(self.modules),
            "affected_dates": sorted(self.db.get_affected_dates()),
        }

        log.info("=" * 60)
        return summary
