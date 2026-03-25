"""
LifeData V4 — Log Sanitizer
core/sanitizer.py

Redacts sensitive patterns from strings before they reach log output.
Used by parser_utils and any other code that logs potentially untrusted
data (raw CSV rows, filenames containing PII, etc.).

Patterns redacted:
  - API keys (long hex/alphanumeric tokens)
  - GPS coordinates (truncated to 2 decimal places)
  - Phone numbers (10+ digit sequences with optional + prefix)
  - Email addresses
"""

import re

# ── Pattern definitions ───────────────────────────────────────

# API keys / tokens: 32+ contiguous hex or base64-ish chars
# Matches: "sk-abc123...", "Bearer AAAA...", long hex strings
_API_KEY_RE = re.compile(
    r"\b[A-Za-z0-9_\-]{32,}\b"
)

# GPS coordinate: number with 3+ decimal digits (e.g., 32.776700 or -96.797000)
# Captures sign, integer part, and decimal part separately so we can truncate
_COORD_RE = re.compile(
    r"(?<![A-Za-z0-9])"       # not preceded by alphanumeric
    r"(-?\d{1,3})"            # integer part (group 1)
    r"\."                     # decimal point
    r"(\d{3,})"              # 3+ decimal digits (group 2) — high precision
    r"(?![A-Za-z0-9])"        # not followed by alphanumeric
)

# Phone numbers: must start with + followed by digits, or look like (NNN) NNN-NNNN
# Avoids matching epoch timestamps (10-digit integers without + prefix)
_PHONE_RE = re.compile(
    r"\+\d[\d\s\-().]{9,}"          # +1-555-123-4567 style
    r"|"
    r"\(\d{3}\)\s*\d{3}[\s\-]\d{4}"  # (555) 123-4567 style
)

# Email addresses
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


# ── Public API ────────────────────────────────────────────────


def redact_api_keys(text: str) -> str:
    """Replace likely API keys/tokens with [REDACTED_KEY]."""
    return _API_KEY_RE.sub("[REDACTED_KEY]", text)


def truncate_coordinates(text: str) -> str:
    """Truncate GPS coordinates to 2 decimal places in a string.

    32.776700 → 32.77***
    -96.797000 → -96.79***
    """
    def _trunc(m: re.Match[str]) -> str:
        integer = m.group(1)
        decimals = m.group(2)
        return f"{integer}.{decimals[:2]}***"
    return _COORD_RE.sub(_trunc, text)


def redact_phones(text: str) -> str:
    """Replace phone-number-like digit sequences with [REDACTED_PHONE]."""
    return _PHONE_RE.sub("[REDACTED_PHONE]", text)


def redact_emails(text: str) -> str:
    """Replace email addresses with [REDACTED_EMAIL]."""
    return _EMAIL_RE.sub("[REDACTED_EMAIL]", text)


def sanitize_for_log(text: str) -> str:
    """Apply all redaction passes to a string before logging.

    Order matters: coordinates before API keys (coordinates are shorter
    and could be falsely matched by the key pattern).
    """
    text = truncate_coordinates(text)
    text = redact_phones(text)
    text = redact_emails(text)
    text = redact_api_keys(text)
    return text
