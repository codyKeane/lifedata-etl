"""
LifeData V4 — Security Hardening Tests
tests/test_security.py

Tests for:
  1. core/sanitizer.py — PII redaction patterns
  2. parser_utils.py sanitizer integration
  3. Orchestrator startup security checks
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ══════════════════════════════════════════════════════════════
# 1. SANITIZER PATTERNS
# ══════════════════════════════════════════════════════════════


class TestSanitizeForLog:

    def test_truncate_gps_high_precision(self):
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("lat=32.776700,lon=-96.797000")
        assert "32.77***" in result
        assert "-96.79***" in result
        # Full precision should NOT appear
        assert "32.776700" not in result
        assert "96.797000" not in result

    def test_truncate_gps_4_decimal(self):
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("32.7767,-96.7970")
        assert "32.77***" in result
        assert "-96.79***" in result

    def test_preserve_low_precision_coords(self):
        """2 decimal places should NOT be truncated (already low precision)."""
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("lat=32.77")
        assert result == "lat=32.77"

    def test_redact_phone_with_plus(self):
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("call from +15551234567")
        assert "+15551234567" not in result
        assert "REDACTED_PHONE" in result

    def test_redact_phone_parens_format(self):
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("call from (555) 123-4567")
        assert "(555) 123-4567" not in result
        assert "REDACTED_PHONE" in result

    def test_preserve_epoch_timestamp(self):
        """10-digit epoch timestamps must NOT be redacted as phone numbers."""
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("1711303200,3-24-26,10:00,-0500,on,85")
        assert "1711303200" in result

    def test_redact_api_key(self):
        from core.sanitizer import sanitize_for_log
        key = "abcdef1234567890abcdef1234567890abcd"
        result = sanitize_for_log(f"key={key}")
        assert key not in result
        assert "REDACTED_KEY" in result

    def test_redact_email(self):
        from core.sanitizer import sanitize_for_log
        result = sanitize_for_log("from user@example.com")
        assert "user@example.com" not in result
        assert "REDACTED_EMAIL" in result

    def test_realistic_geofence_csv(self):
        """Realistic geofence CSV line should have coords truncated but epoch preserved."""
        from core.sanitizer import sanitize_for_log
        raw = "1711303200,32.7767,-96.7970,15,0,1,0"
        result = sanitize_for_log(raw)
        assert "1711303200" in result
        assert "32.77***" in result
        assert "-96.79***" in result

    def test_mixed_content(self):
        """Multiple sensitive patterns in one string."""
        from core.sanitizer import sanitize_for_log
        raw = "user@evil.com called +15551234567 at 32.776700,-96.797000"
        result = sanitize_for_log(raw)
        assert "evil.com" not in result
        assert "+15551234567" not in result
        assert "32.776700" not in result

    def test_empty_string(self):
        from core.sanitizer import sanitize_for_log
        assert sanitize_for_log("") == ""

    def test_safe_string_unchanged(self):
        from core.sanitizer import sanitize_for_log
        safe = "device.battery pulse 85.0"
        assert sanitize_for_log(safe) == safe


class TestIndividualSanitizers:

    def test_redact_api_keys_standalone(self):
        from core.sanitizer import redact_api_keys
        assert "REDACTED_KEY" in redact_api_keys("x" * 32)
        # Short strings should NOT match
        assert redact_api_keys("short") == "short"

    def test_truncate_coordinates_standalone(self):
        from core.sanitizer import truncate_coordinates
        assert truncate_coordinates("32.776700") == "32.77***"
        assert truncate_coordinates("-0.12345") == "-0.12***"
        assert truncate_coordinates("100.999999") == "100.99***"

    def test_redact_phones_standalone(self):
        from core.sanitizer import redact_phones
        assert "REDACTED_PHONE" in redact_phones("+15551234567")
        # No match for short numbers
        assert redact_phones("12345") == "12345"

    def test_redact_emails_standalone(self):
        from core.sanitizer import redact_emails
        assert "REDACTED_EMAIL" in redact_emails("a@b.com")


# ══════════════════════════════════════════════════════════════
# 2. PARSER_UTILS SANITIZER INTEGRATION
# ══════════════════════════════════════════════════════════════


class TestParserUtilsSanitization:

    def test_raw_line_with_coords_is_sanitized_in_log(self, tmp_path, caplog):
        """When a parse error occurs on a line with GPS coords, the logged
        raw content should have coords truncated."""
        import logging

        from core.parser_utils import safe_parse_rows

        csv_path = str(tmp_path / "test.csv")
        # Line with high-precision GPS that will cause a parse error
        with open(csv_path, "w") as f:
            f.write("1711303200,32.776700,-96.797000,crash_here\n")

        def exploding_fn(fields, line_num):
            raise ValueError("boom")

        with caplog.at_level(logging.WARNING, logger="lifedata.parser_utils"):
            safe_parse_rows(csv_path, exploding_fn, "test")

        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warn_msgs) >= 1
        # Full precision coords should NOT appear in the log
        assert "32.776700" not in warn_msgs[0]
        assert "-96.797000" not in warn_msgs[0]
        # Truncated coords SHOULD appear
        assert "32.77***" in warn_msgs[0]

    def test_raw_line_with_phone_is_sanitized_in_log(self, tmp_path, caplog):
        """Phone numbers in error-logged raw lines should be redacted."""
        import logging

        from core.parser_utils import safe_parse_rows

        csv_path = str(tmp_path / "test.csv")
        with open(csv_path, "w") as f:
            f.write("1711303200,call,+15551234567,John Doe,180\n")

        def exploding_fn(fields, line_num):
            raise ValueError("boom")

        with caplog.at_level(logging.WARNING, logger="lifedata.parser_utils"):
            safe_parse_rows(csv_path, exploding_fn, "test")

        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert "+15551234567" not in warn_msgs[0]


# ══════════════════════════════════════════════════════════════
# 3. ORCHESTRATOR STARTUP SECURITY CHECKS
# ══════════════════════════════════════════════════════════════


class TestStartupSecurityChecks:

    def _make_lifedata_env(self, tmp_path):
        """Create a minimal ~/LifeData-like structure for testing."""
        ld = tmp_path / "LifeData"
        ld.mkdir()
        (ld / "db").mkdir()
        (ld / "raw" / "LifeData").mkdir(parents=True)
        (ld / "media").mkdir()
        (ld / "reports").mkdir()
        (ld / "logs").mkdir()

        env_path = ld / ".env"
        env_path.write_text("WEATHER_API_KEY=test\n")
        os.chmod(str(env_path), 0o600)

        return ld

    def test_env_permission_warning(self, tmp_path, caplog):
        """Warn if .env permissions are not 0600."""
        import logging

        from core.orchestrator import Orchestrator

        ld = self._make_lifedata_env(tmp_path)
        env_path = ld / ".env"
        os.chmod(str(env_path), 0o644)  # too permissive

        orch = Orchestrator.__new__(Orchestrator)
        # Temporarily point HOME to our tmp_path
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            with caplog.at_level(logging.WARNING):
                warnings = orch._check_startup_security(str(ld / "config.yaml"))
        finally:
            if old_home:
                os.environ["HOME"] = old_home

        assert any(".env" in w and "0o644" in w for w in warnings)

    def test_stfolder_warning(self, tmp_path, caplog):
        """Warn if ~/LifeData/ contains .stfolder/ (Syncthing marker)."""
        import logging

        from core.orchestrator import Orchestrator

        ld = self._make_lifedata_env(tmp_path)
        (ld / ".stfolder").mkdir()

        orch = Orchestrator.__new__(Orchestrator)
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            with caplog.at_level(logging.WARNING):
                warnings = orch._check_startup_security(str(ld / "config.yaml"))
        finally:
            if old_home:
                os.environ["HOME"] = old_home

        assert any(".stfolder" in w for w in warnings)

    def test_clean_environment_passes(self, tmp_path, caplog):
        """When everything is correctly configured, no warnings should fire
        (except possibly disk encryption which is best-effort)."""
        import logging

        from core.orchestrator import Orchestrator

        ld = self._make_lifedata_env(tmp_path)
        os.chmod(str(ld), 0o700)
        os.chmod(str(ld / ".env"), 0o600)

        # Create a config.yaml with proper permissions
        cfg = ld / "config.yaml"
        cfg.write_text("# dummy\n")
        os.chmod(str(cfg), 0o600)

        orch = Orchestrator.__new__(Orchestrator)
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            with caplog.at_level(logging.WARNING):
                warnings = orch._check_startup_security(str(cfg))
        finally:
            if old_home:
                os.environ["HOME"] = old_home

        # Filter out disk encryption warnings (best-effort, machine-dependent)
        non_encryption = [w for w in warnings if "encryption" not in w.lower()]
        assert non_encryption == [], f"Unexpected warnings: {non_encryption}"

    def test_directory_permission_warning(self, tmp_path, caplog):
        """Warn if ~/LifeData/ permissions are not 0700."""
        import logging

        from core.orchestrator import Orchestrator

        ld = self._make_lifedata_env(tmp_path)
        os.chmod(str(ld), 0o755)  # too permissive

        orch = Orchestrator.__new__(Orchestrator)
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(tmp_path)
        try:
            with caplog.at_level(logging.WARNING):
                warnings = orch._check_startup_security(str(ld / "config.yaml"))
        finally:
            if old_home:
                os.environ["HOME"] = old_home

        assert any("~/LifeData/" in w and "0o755" in w for w in warnings)
