"""Tests for staging field name collision detection (CR-1).

When a staging record contains a top-level field whose name matches a reserved
prompt-context namespace (any member of ``SPECIAL_NAMESPACES``), the pipeline
must reject the data with an actionable error — not silently mis-route values
at prompt-build time.
"""

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging.field_validation import (
    validate_staging_field_names,
)


class TestValidateStagingFieldNames:
    """Collision detection for reserved namespace names in staging data."""

    @pytest.mark.parametrize(
        "field",
        ["source", "version", "workflow", "seed", "prompt", "schema", "action"],
    )
    def test_each_reserved_name_raises(self, field):
        records = [{"id": "1", field: "value"}]
        with pytest.raises(ConfigValidationError, match=field):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_multiple_collisions_reported(self):
        records = [{"source": "a.md", "version": "1.0", "title": "doc"}]
        with pytest.raises(ConfigValidationError, match="source.*version|version.*source"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_no_collision_list_passes(self):
        records = [{"id": "1", "url": "http://example.com", "page_content": "text"}]
        validate_staging_field_names(records, "/fake/staging/data.json")

    def test_no_collision_dict_passes(self):
        record = {"id": "1", "title": "doc", "body": "text"}
        validate_staging_field_names(record, "/fake/staging/data.json")

    def test_dict_input_collision_raises(self):
        record = {"source": "file.md", "content_text": "text"}
        with pytest.raises(ConfigValidationError, match="source"):
            validate_staging_field_names(record, "/fake/staging/data.json")

    def test_collision_on_second_record(self):
        """Collision only on record [1] — must not be missed."""
        records = [
            {"id": "1", "title": "safe"},
            {"id": "2", "source": "Architecture.md"},
        ]
        with pytest.raises(ConfigValidationError, match="source"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_collision_on_last_record(self):
        records = [
            {"id": "1", "title": "ok"},
            {"id": "2", "title": "ok"},
            {"id": "3", "version": "2.0"},
        ]
        with pytest.raises(ConfigValidationError, match="version"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_non_dict_first_then_dict_with_collision(self):
        """First element is a string, second is a dict with collision."""
        records = ["plain text", {"source": "file.md", "body": "text"}]
        with pytest.raises(ConfigValidationError, match="source"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_non_dict_elements_skipped(self):
        """Non-dict elements in list are silently skipped, dicts still checked."""
        records = ["string1", 42, None, {"id": "1", "title": "safe"}]
        validate_staging_field_names(records, "/fake/staging/data.json")
