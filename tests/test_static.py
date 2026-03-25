"""
LifeData V4 — Static Analysis CI Gate
tests/test_static.py

Runs mypy as a subprocess and asserts exit code 0 so that type regressions
are caught by the normal test suite (pytest / make test / CI).
"""

import subprocess
import sys

import pytest


class TestMypy:
    """Ensure mypy passes on both core/ (strict) and modules/ (standard)."""

    @pytest.mark.timeout(120)
    def test_mypy_strict_core(self) -> None:
        """mypy --strict core/ must pass with zero errors."""
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--strict", "core/"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"mypy --strict core/ failed:\n{result.stdout}\n{result.stderr}"
        )

    @pytest.mark.timeout(120)
    def test_mypy_modules(self) -> None:
        """mypy modules/ must pass with zero errors."""
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "modules/"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"mypy modules/ failed:\n{result.stdout}\n{result.stderr}"
        )
