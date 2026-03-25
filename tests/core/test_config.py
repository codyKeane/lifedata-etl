"""
Tests for core/config.py — typed config loading and validation.
"""

import os
import textwrap

import pytest
import yaml

from core.config import load_config
from core.config_schema import ConfigValidationError


def _minimal_config(tmp_path, overrides=None):
    """Write a minimal valid config.yaml and return its path.

    Creates the directory structure that path validation expects.
    """
    # Create directories that the config references
    (tmp_path / "db").mkdir(exist_ok=True)
    (tmp_path / "raw" / "LifeData").mkdir(parents=True, exist_ok=True)
    (tmp_path / "media").mkdir(exist_ok=True)
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)

    config = {
        "lifedata": {
            "version": "4.0",
            "timezone": "America/Chicago",
            "db_path": str(tmp_path / "db" / "test.db"),
            "raw_base": str(tmp_path / "raw" / "LifeData"),
            "media_base": str(tmp_path / "media"),
            "reports_dir": str(tmp_path / "reports"),
            "log_path": str(tmp_path / "logs" / "etl.log"),
            "security": {
                "syncthing_relay_enabled": False,
                "module_allowlist": ["device"],
            },
            "modules": {
                "device": {"enabled": True},
                "environment": {"enabled": False},
                "world": {"enabled": False},
            },
        }
    }

    if overrides:
        _deep_merge(config, overrides)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False))

    # Write an empty .env so load_config doesn't warn
    (tmp_path / ".env").write_text("")

    return str(config_path), str(tmp_path / ".env")


def _deep_merge(base, override):
    """Recursively merge override into base dict."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ──────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────


class TestValidConfigLoads:

    def test_minimal_valid_config(self, tmp_path):
        config_path, env_path = _minimal_config(tmp_path)
        result = load_config(config_path, env_path)
        assert result.lifedata.version == "4.0"
        assert result.lifedata.timezone == "America/Chicago"

    def test_returns_typed_object(self, tmp_path):
        config_path, env_path = _minimal_config(tmp_path)
        result = load_config(config_path, env_path)
        # Verify typed attribute access works
        assert result.lifedata.security.syncthing_relay_enabled is False
        assert result.lifedata.security.module_allowlist == ["device"]
        assert result.lifedata.modules.device.enabled is True


# ──────────────────────────────────────────────────────────────
# Missing required field
# ──────────────────────────────────────────────────────────────


class TestMissingRequiredField:

    def test_missing_version_raises(self, tmp_path):
        (tmp_path / "db").mkdir()
        (tmp_path / "raw" / "LifeData").mkdir(parents=True)
        (tmp_path / "media").mkdir()
        (tmp_path / "reports").mkdir()
        (tmp_path / "logs").mkdir()

        config = {
            "lifedata": {
                # version intentionally missing
                "timezone": "America/Chicago",
                "db_path": str(tmp_path / "db" / "test.db"),
                "raw_base": str(tmp_path / "raw" / "LifeData"),
                "media_base": str(tmp_path / "media"),
                "reports_dir": str(tmp_path / "reports"),
                "log_path": str(tmp_path / "logs" / "etl.log"),
                "security": {
                    "syncthing_relay_enabled": False,
                    "module_allowlist": ["device"],
                },
            }
        }

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))
        (tmp_path / ".env").write_text("")

        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(str(config_path), str(tmp_path / ".env"))
        assert "version" in str(exc_info.value).lower()


# ──────────────────────────────────────────────────────────────
# Invalid timezone
# ──────────────────────────────────────────────────────────────


class TestInvalidTimezone:

    def test_bogus_timezone_raises(self, tmp_path):
        config_path, env_path = _minimal_config(
            tmp_path,
            {"lifedata": {"timezone": "Mars/Olympus_Mons"}},
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(config_path, env_path)
        assert "timezone" in str(exc_info.value).lower()


# ──────────────────────────────────────────────────────────────
# Syncthing relay hard error
# ──────────────────────────────────────────────────────────────


class TestSyncthingRelay:

    def test_relay_enabled_raises(self, tmp_path):
        config_path, env_path = _minimal_config(
            tmp_path,
            {"lifedata": {"security": {"syncthing_relay_enabled": True}}},
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(config_path, env_path)
        assert "relay" in str(exc_info.value).lower()


# ──────────────────────────────────────────────────────────────
# Unresolvable env var warns but doesn't crash
# ──────────────────────────────────────────────────────────────


class TestUnresolvableEnvVar:

    def test_unresolved_env_var_warns_not_crashes(self, tmp_path, monkeypatch):
        """Config with ${NONEXISTENT_KEY} in a non-critical field should load."""
        monkeypatch.delenv("NONEXISTENT_KEY_XYZ", raising=False)

        config_path, env_path = _minimal_config(
            tmp_path,
            {
                "lifedata": {
                    "security": {
                        "syncthing_api_key": "${NONEXISTENT_KEY_XYZ}",
                    }
                }
            },
        )
        # Should not raise — unresolved env vars become empty strings with a warning
        result = load_config(config_path, env_path)
        assert result.lifedata.security.syncthing_api_key == ""


# ──────────────────────────────────────────────────────────────
# Invalid path
# ──────────────────────────────────────────────────────────────


class TestInvalidPath:

    def test_nonexistent_parent_dir_raises(self, tmp_path):
        config_path, env_path = _minimal_config(
            tmp_path,
            {"lifedata": {"db_path": "/nonexistent/deeply/nested/path/db.db"}},
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(config_path, env_path)
        assert "db_path" in str(exc_info.value)


# ──────────────────────────────────────────────────────────────
# Module allowlist with nonexistent module
# ──────────────────────────────────────────────────────────────


class TestModuleAllowlist:

    def test_nonexistent_module_raises(self, tmp_path):
        config_path, env_path = _minimal_config(
            tmp_path,
            {
                "lifedata": {
                    "security": {
                        "module_allowlist": ["device", "completely_fake_module"],
                    }
                }
            },
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            load_config(config_path, env_path)
        assert "completely_fake_module" in str(exc_info.value)
