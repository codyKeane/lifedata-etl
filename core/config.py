"""
LifeData V4 — Configuration Loader
core/config.py

Loads config.yaml, resolves ${ENV_VAR} placeholders from os.environ
(with .env pre-loaded), validates via pydantic schema, and returns
a typed RootConfig object. Fails fast with ALL validation errors.
"""

import logging
import os
import re

import yaml
from dotenv import load_dotenv

from core.config_schema import RootConfig, validate_config

log = logging.getLogger("lifedata.config")

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_var_match(m: re.Match[str]) -> str:
    """Resolve a single ${ENV_VAR} match, warning if unset."""
    var_name = m.group(1)
    value = os.environ.get(var_name)
    if value is None:
        log.warning(
            "Environment variable '%s' is not set — "
            "replaced with empty string in config",
            var_name,
        )
        return ""
    return value


def _resolve_env_vars(obj: object) -> None:
    """Recursively resolve ${ENV_VAR} patterns in config values (in-place)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and "${" in value:
                obj[key] = _ENV_VAR_RE.sub(_resolve_env_var_match, value)
            elif isinstance(value, dict | list):
                _resolve_env_vars(value)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and "${" in item:
                obj[i] = _ENV_VAR_RE.sub(_resolve_env_var_match, item)
            elif isinstance(item, dict | list):
                _resolve_env_vars(item)


def load_config(
    path: str = "~/LifeData/config.yaml",
    env_path: str = "~/LifeData/.env",
) -> RootConfig:
    """Load, resolve, and validate config.yaml.

    Steps:
        1. Load .env file for API key resolution
        2. Read YAML from path
        3. Resolve ${ENV_VAR} references from os.environ
        4. Validate via pydantic schema
        5. Return typed RootConfig

    Raises:
        ConfigValidationError: with ALL validation failures listed.
        FileNotFoundError: if config.yaml doesn't exist.
    """
    # Load .env (must be chmod 600, never in Syncthing folder)
    env_expanded = os.path.expanduser(env_path)
    if os.path.exists(env_expanded):
        load_dotenv(env_expanded, override=False)
    else:
        log.warning(".env file not found at %s — API keys may be missing", env_expanded)

    # Read YAML
    config_expanded = os.path.expanduser(path)
    with open(config_expanded, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve env vars in-place
    _resolve_env_vars(config)

    # Validate and return typed config
    return validate_config(config)
