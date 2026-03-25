"""
Tests for core/orchestrator.py — path safety, env var resolution, module allowlist.
"""

import os
import pytest

from core.config import _resolve_env_vars
from core.orchestrator import Orchestrator


# ──────────────────────────────────────────────────────────────
# Path safety — _is_safe_path
# ──────────────────────────────────────────────────────────────


class TestIsSafePath:
    """Ensure _is_safe_path blocks path traversal attacks."""

    @pytest.fixture
    def raw_base(self, tmp_path):
        """Create a realistic raw_base directory structure."""
        raw = tmp_path / "raw" / "LifeData"
        raw.mkdir(parents=True)
        (raw / "device").mkdir()
        (raw / "device" / "battery_2026.csv").write_text("data")
        # Also create raw/api for world module
        api = tmp_path / "raw" / "api"
        api.mkdir()
        (api / "headlines.json").write_text("{}")
        return str(raw)

    def test_file_inside_raw_base(self, raw_base):
        safe_file = os.path.join(raw_base, "device", "battery_2026.csv")
        assert Orchestrator._is_safe_path(safe_file, raw_base)

    def test_traversal_blocked(self, raw_base):
        bad_path = os.path.join(raw_base, "..", "..", "etc", "passwd")
        assert not Orchestrator._is_safe_path(bad_path, raw_base)

    def test_absolute_outside_blocked(self, raw_base):
        assert not Orchestrator._is_safe_path("/etc/passwd", raw_base)

    def test_raw_api_sibling_allowed(self, raw_base, tmp_path):
        """Files under raw/api/ should be accepted (world module data)."""
        api_file = str(tmp_path / "raw" / "api" / "headlines.json")
        assert Orchestrator._is_safe_path(api_file, raw_base)

    def test_symlink_traversal_blocked(self, raw_base, tmp_path):
        """Symlinks that escape raw_base should be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.csv"
        secret.write_text("secret")

        link = os.path.join(raw_base, "evil_link.csv")
        try:
            os.symlink(str(secret), link)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        assert not Orchestrator._is_safe_path(link, raw_base)

    def test_empty_path(self, raw_base):
        assert not Orchestrator._is_safe_path("", raw_base)

    def test_raw_base_itself(self, raw_base):
        assert Orchestrator._is_safe_path(raw_base, raw_base)


# ──────────────────────────────────────────────────────────────
# Environment variable resolution
# ──────────────────────────────────────────────────────────────


class TestResolveEnvVars:
    """Test recursive ${ENV_VAR} substitution in config dicts."""

    def test_simple_substitution(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "secret123")
        config = {"api_key": "${TEST_API_KEY}"}
        _resolve_env_vars(config)
        assert config["api_key"] == "secret123"

    def test_nested_dict(self, monkeypatch):
        monkeypatch.setenv("INNER_VAR", "resolved")
        config = {"outer": {"inner": "${INNER_VAR}"}}
        _resolve_env_vars(config)
        assert config["outer"]["inner"] == "resolved"

    def test_list_values(self, monkeypatch):
        monkeypatch.setenv("LIST_VAR", "item")
        config = {"items": ["${LIST_VAR}", "static"]}
        _resolve_env_vars(config)
        assert config["items"] == ["item", "static"]

    def test_unset_var_becomes_empty(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        config = {"key": "${NONEXISTENT_VAR}"}
        _resolve_env_vars(config)
        assert config["key"] == ""

    def test_no_substitution_without_marker(self):
        config = {"key": "plain_value"}
        _resolve_env_vars(config)
        assert config["key"] == "plain_value"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("A", "hello")
        monkeypatch.setenv("B", "world")
        config = {"msg": "${A} ${B}"}
        _resolve_env_vars(config)
        assert config["msg"] == "hello world"

    def test_non_string_values_untouched(self):
        config = {"count": 42, "flag": True, "ratio": 3.14}
        _resolve_env_vars(config)
        assert config == {"count": 42, "flag": True, "ratio": 3.14}
