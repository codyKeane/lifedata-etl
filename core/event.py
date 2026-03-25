"""
LifeData V4 — Event Model
core/event.py

The fundamental unit of data in the LifeData system.
Every data point — from screen unlocks to mood scores to geomagnetic readings —
is represented as an Event conforming to the Universal Event Schema.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Maximum field lengths to prevent database bloat from malformed input
MAX_VALUE_TEXT_LEN = 50_000
MAX_VALUE_JSON_LEN = 100_000
MAX_TAGS_LEN = 1_000


@dataclass
class Event:
    """A single data point in the LifeData system.

    Every module parser produces Event objects. The orchestrator handles
    database insertion via INSERT OR REPLACE on raw_source_id.

    Attributes:
        timestamp_utc: ISO 8601 UTC timestamp of when the event occurred.
        timestamp_local: ISO 8601 local-time timestamp.
        timezone_offset: Timezone offset string, e.g. '-0500'.
        source_module: Dot-notation source identifier, e.g. 'device.screen'.
        event_type: Event subtype, e.g. 'screen_on', 'measurement'.
        value_numeric: Optional numeric payload (mood=7, bpm=72, Kp=4.3).
        value_text: Optional text payload (headline, dream journal).
        value_json: Optional complex payload as a JSON string.
        tags: Optional comma-separated tags for fast filtering.
        location_lat: Optional GPS latitude.
        location_lon: Optional GPS longitude.
        media_ref: Optional UUID pointing to the media table.
        confidence: Reliability score 0.0–1.0 (see Confidence Policy in ALPHA).
        parser_version: Semver of the module parser that created this event.
        created_at: ISO 8601 timestamp of when the ETL ingested this row.
    """

    timestamp_utc: str
    timestamp_local: str
    timezone_offset: str
    source_module: str
    event_type: str
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    value_json: Optional[str] = None
    tags: Optional[str] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    media_ref: Optional[str] = None
    confidence: float = 1.0
    parser_version: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Ephemeral provenance trace — NOT stored in the database.
    # Set by safe_parse_rows() for debugging: which file, line, and parser
    # produced this event.  Example:
    #   "file=screen_2026-03-22.csv:line=47:parser=device:v=1.0.0"
    provenance: Optional[str] = None

    @property
    def raw_source_id(self) -> str:
        """Deduplication hash.

        Two events with the same raw_source_id are considered identical
        and will overwrite each other via INSERT OR REPLACE.

        Floats are normalized to :.6f for hash stability across Python versions.
        None values are encoded as the literal string 'None' for consistency.
        """
        num_str = (
            f"{self.value_numeric:.6f}" if self.value_numeric is not None else "None"
        )
        raw = (
            f"{self.timestamp_utc}|{self.source_module}|"
            f"{self.event_type}|{self.value_text}|{num_str}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @property
    def event_id(self) -> str:
        """Deterministic UUID derived from raw_source_id.

        Stable across ETL re-runs:
        - INSERT OR REPLACE never changes the primary key.
        - media_ref foreign keys remain valid.
        - Cached correlation pointers don't go stale.
        """
        digest = hashlib.sha256(self.raw_source_id.encode("utf-8")).hexdigest()
        return str(uuid.UUID(hex=digest[:32]))

    def validate(self) -> list[str]:
        """Validate event data, returning a list of error messages.

        Returns an empty list if the event is valid.
        This is preferred over a boolean so callers can log specific issues.
        """
        errors: list[str] = []

        if not self.timestamp_utc:
            errors.append("timestamp_utc is required")

        if not self.timestamp_local:
            errors.append("timestamp_local is required")

        if not self.timezone_offset:
            errors.append("timezone_offset is required")

        if not self.source_module:
            errors.append("source_module is required")
        elif "." not in self.source_module:
            errors.append(
                f"source_module must use dot-notation, got '{self.source_module}'"
            )

        if not self.event_type:
            errors.append("event_type is required")

        if (
            self.value_numeric is None
            and self.value_text is None
            and self.value_json is None
        ):
            errors.append(
                "at least one of value_numeric, value_text, or value_json is required"
            )

        if not (0.0 <= self.confidence <= 1.0):
            errors.append(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )

        # Validate value_json is actually valid JSON
        if self.value_json is not None:
            try:
                json.loads(self.value_json)
            except (json.JSONDecodeError, TypeError):
                errors.append("value_json is not valid JSON")

        # Enforce size limits to prevent database bloat
        if self.value_text and len(self.value_text) > MAX_VALUE_TEXT_LEN:
            errors.append(
                f"value_text exceeds {MAX_VALUE_TEXT_LEN} chars "
                f"(got {len(self.value_text)})"
            )
        if self.value_json and len(self.value_json) > MAX_VALUE_JSON_LEN:
            errors.append(
                f"value_json exceeds {MAX_VALUE_JSON_LEN} chars "
                f"(got {len(self.value_json)})"
            )
        if self.tags and len(self.tags) > MAX_TAGS_LEN:
            errors.append(f"tags exceeds {MAX_TAGS_LEN} chars (got {len(self.tags)})")

        return errors

    @property
    def is_valid(self) -> bool:
        """Convenience: True if validate() returns no errors."""
        return len(self.validate()) == 0

    def to_db_tuple(self) -> tuple:
        """Return a tuple matching the INSERT column order for the events table.

        Column order:
            event_id, timestamp_utc, timestamp_local, timezone_offset,
            source_module, event_type,
            value_numeric, value_text, value_json, tags,
            location_lat, location_lon, media_ref, confidence,
            raw_source_id, parser_version, created_at
        """
        return (
            self.event_id,
            self.timestamp_utc,
            self.timestamp_local,
            self.timezone_offset,
            self.source_module,
            self.event_type,
            self.value_numeric,
            self.value_text,
            self.value_json,
            self.tags,
            self.location_lat,
            self.location_lon,
            self.media_ref,
            self.confidence,
            self.raw_source_id,
            self.parser_version,
            self.created_at,
        )

    def __repr__(self) -> str:
        val = (
            self.value_numeric
            if self.value_numeric is not None
            else (self.value_text[:40] if self.value_text else self.value_json)
        )
        prov = f" [{self.provenance}]" if self.provenance else ""
        return (
            f"Event({self.source_module}/{self.event_type} "
            f"@ {self.timestamp_utc} = {val}{prov})"
        )
