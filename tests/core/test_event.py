"""
Tests for core/event.py — Event model validation edge cases.
"""

import json

from core.event import MAX_TAGS_LEN, MAX_VALUE_JSON_LEN, MAX_VALUE_TEXT_LEN


class TestEventValidation:
    """Validation edge cases for the Event dataclass."""

    def test_valid_event_passes(self, valid_event):
        assert valid_event.is_valid
        assert valid_event.validate() == []

    def test_missing_timestamp_utc(self, valid_event_factory):
        e = valid_event_factory(timestamp_utc="")
        errors = e.validate()
        assert any("timestamp_utc" in err for err in errors)

    def test_missing_timestamp_local(self, valid_event_factory):
        e = valid_event_factory(timestamp_local="")
        assert not e.is_valid

    def test_missing_timezone_offset(self, valid_event_factory):
        e = valid_event_factory(timezone_offset="")
        assert not e.is_valid

    def test_missing_source_module(self, valid_event_factory):
        e = valid_event_factory(source_module="")
        errors = e.validate()
        assert any("source_module" in err for err in errors)

    def test_source_module_no_dot(self, valid_event_factory):
        e = valid_event_factory(source_module="device")
        errors = e.validate()
        assert any("dot-notation" in err for err in errors)

    def test_source_module_with_dot(self, valid_event_factory):
        e = valid_event_factory(source_module="device.battery")
        assert e.is_valid

    def test_missing_event_type(self, valid_event_factory):
        e = valid_event_factory(event_type="")
        assert not e.is_valid

    def test_no_value_fields_fails(self, valid_event_factory):
        e = valid_event_factory(value_numeric=None, value_text=None, value_json=None)
        errors = e.validate()
        assert any("at least one" in err for err in errors)

    def test_only_value_text_valid(self, valid_event_factory):
        e = valid_event_factory(value_numeric=None, value_text="hello")
        assert e.is_valid

    def test_only_value_json_valid(self, valid_event_factory):
        e = valid_event_factory(value_numeric=None, value_json='{"key": "val"}')
        assert e.is_valid

    def test_confidence_below_zero(self, valid_event_factory):
        e = valid_event_factory(confidence=-0.1)
        errors = e.validate()
        assert any("confidence" in err for err in errors)

    def test_confidence_above_one(self, valid_event_factory):
        e = valid_event_factory(confidence=1.1)
        assert not e.is_valid

    def test_confidence_boundary_zero(self, valid_event_factory):
        e = valid_event_factory(confidence=0.0)
        assert e.is_valid

    def test_confidence_boundary_one(self, valid_event_factory):
        e = valid_event_factory(confidence=1.0)
        assert e.is_valid

    def test_invalid_json_in_value_json(self, valid_event_factory):
        e = valid_event_factory(value_numeric=None, value_json="not valid json")
        errors = e.validate()
        assert any("not valid JSON" in err for err in errors)

    def test_value_text_exceeds_max(self, valid_event_factory):
        e = valid_event_factory(value_text="x" * (MAX_VALUE_TEXT_LEN + 1))
        errors = e.validate()
        assert any("value_text exceeds" in err for err in errors)

    def test_value_text_at_max(self, valid_event_factory):
        e = valid_event_factory(value_text="x" * MAX_VALUE_TEXT_LEN)
        assert e.is_valid

    def test_value_json_exceeds_max(self, valid_event_factory):
        big_json = json.dumps({"data": "x" * MAX_VALUE_JSON_LEN})
        e = valid_event_factory(value_numeric=None, value_json=big_json)
        errors = e.validate()
        assert any("value_json exceeds" in err for err in errors)

    def test_tags_exceeds_max(self, valid_event_factory):
        e = valid_event_factory(tags="t," * (MAX_TAGS_LEN + 1))
        errors = e.validate()
        assert any("tags exceeds" in err for err in errors)

    def test_multiple_errors_returned(self, valid_event_factory):
        e = valid_event_factory(
            source_module="",
            event_type="",
            value_numeric=None,
            confidence=5.0,
        )
        errors = e.validate()
        assert len(errors) >= 3


class TestEventDeduplication:
    """Deterministic event_id and raw_source_id generation."""

    def test_same_input_same_raw_source_id(self, valid_event_factory):
        e1 = valid_event_factory()
        e2 = valid_event_factory()
        assert e1.raw_source_id == e2.raw_source_id

    def test_same_input_same_event_id(self, valid_event_factory):
        e1 = valid_event_factory()
        e2 = valid_event_factory()
        assert e1.event_id == e2.event_id

    def test_different_timestamp_different_id(self, valid_event_factory):
        e1 = valid_event_factory(timestamp_utc="2026-03-24T15:00:00+00:00")
        e2 = valid_event_factory(timestamp_utc="2026-03-24T16:00:00+00:00")
        assert e1.event_id != e2.event_id

    def test_different_module_different_id(self, valid_event_factory):
        e1 = valid_event_factory(source_module="device.battery")
        e2 = valid_event_factory(source_module="device.screen")
        assert e1.event_id != e2.event_id

    def test_different_event_type_different_id(self, valid_event_factory):
        e1 = valid_event_factory(event_type="pulse")
        e2 = valid_event_factory(event_type="charge_start")
        assert e1.event_id != e2.event_id

    def test_different_numeric_different_id(self, valid_event_factory):
        e1 = valid_event_factory(value_numeric=85.0)
        e2 = valid_event_factory(value_numeric=86.0)
        assert e1.event_id != e2.event_id

    def test_different_value_json_different_id(self, valid_event_factory):
        e1 = valid_event_factory(value_json='{"status": "start"}')
        e2 = valid_event_factory(value_json='{"status": "end"}')
        assert e1.raw_source_id != e2.raw_source_id
        assert e1.event_id != e2.event_id

    def test_different_value_text_different_id(self, valid_event_factory):
        e1 = valid_event_factory(value_text="alpha")
        e2 = valid_event_factory(value_text="beta")
        assert e1.raw_source_id != e2.raw_source_id
        assert e1.event_id != e2.event_id

    def test_float_precision_stability(self, valid_event_factory):
        """Floats normalized to .6f — close but distinct values differ."""
        e1 = valid_event_factory(value_numeric=85.0000001)
        e2 = valid_event_factory(value_numeric=85.0000002)
        # Both round to 85.000000 at 6 decimal places
        assert e1.raw_source_id == e2.raw_source_id

    def test_none_numeric_deterministic(self, valid_event_factory):
        e1 = valid_event_factory(value_numeric=None, value_text="test")
        e2 = valid_event_factory(value_numeric=None, value_text="test")
        assert e1.raw_source_id == e2.raw_source_id

    def test_event_id_is_valid_uuid(self, valid_event):
        import uuid

        parsed = uuid.UUID(valid_event.event_id)
        assert str(parsed) == valid_event.event_id

    def test_raw_source_id_is_32_hex(self, valid_event):
        assert len(valid_event.raw_source_id) == 32
        assert all(c in "0123456789abcdef" for c in valid_event.raw_source_id)

    def test_created_at_does_not_affect_dedup(self, valid_event_factory):
        """created_at is not part of the hash — re-ingestion is idempotent."""
        e1 = valid_event_factory(created_at="2026-03-24T00:00:00")
        e2 = valid_event_factory(created_at="2026-03-25T00:00:00")
        assert e1.event_id == e2.event_id

    def test_confidence_does_not_affect_dedup(self, valid_event_factory):
        e1 = valid_event_factory(confidence=1.0)
        e2 = valid_event_factory(confidence=0.5)
        assert e1.event_id == e2.event_id

    def test_tags_do_not_affect_dedup(self, valid_event_factory):
        e1 = valid_event_factory(tags="a,b")
        e2 = valid_event_factory(tags="c,d")
        assert e1.event_id == e2.event_id


class TestEventToDbTuple:
    """Ensure to_db_tuple() matches INSERT column order."""

    def test_tuple_length(self, valid_event):
        t = valid_event.to_db_tuple()
        assert len(t) == 17

    def test_tuple_field_order(self, valid_event):
        t = valid_event.to_db_tuple()
        assert t[0] == valid_event.event_id
        assert t[1] == valid_event.timestamp_utc
        assert t[4] == valid_event.source_module
        assert t[5] == valid_event.event_type
        assert t[6] == valid_event.value_numeric
        assert t[13] == valid_event.confidence
        assert t[14] == valid_event.raw_source_id

    def test_repr_does_not_crash(self, valid_event):
        r = repr(valid_event)
        assert "device.battery" in r
