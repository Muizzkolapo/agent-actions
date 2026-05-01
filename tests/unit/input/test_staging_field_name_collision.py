"""Tests for staging field name collision detection (P5-010 / CR-1).

When a staging record contains a top-level field whose name matches a reserved
prompt-context namespace (``source``, ``version``, ``workflow``, etc.), the
pipeline must reject the data with an actionable error — not silently mis-route
values at prompt-build time.
"""

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging.field_validation import (
    validate_staging_field_names,
)


class TestValidateStagingFieldNames:
    """Collision detection for reserved namespace names in staging data."""

    def test_field_named_source_raises(self):
        records = [{"id": "1", "source": "Architecture.md", "page_content": "text"}]
        with pytest.raises(ConfigValidationError, match="source"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_field_named_version_raises(self):
        records = [{"id": "1", "version": "2.0", "title": "doc"}]
        with pytest.raises(ConfigValidationError, match="version"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_field_named_workflow_raises(self):
        records = [{"id": "1", "workflow": "main"}]
        with pytest.raises(ConfigValidationError, match="workflow"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_field_named_seed_raises(self):
        records = [{"id": "1", "seed": 42}]
        with pytest.raises(ConfigValidationError, match="seed"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_multiple_collisions_reported(self):
        records = [{"source": "a.md", "version": "1.0", "title": "doc"}]
        with pytest.raises(ConfigValidationError, match="source.*version|version.*source"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_no_collision_passes(self):
        records = [{"id": "1", "url": "http://example.com", "page_content": "text"}]
        validate_staging_field_names(records, "/fake/staging/data.json")

    def test_dict_input_checked(self):
        record = {"source": "file.md", "content": "text"}
        with pytest.raises(ConfigValidationError, match="source"):
            validate_staging_field_names(record, "/fake/staging/data.json")

    def test_empty_input_passes(self):
        validate_staging_field_names([], "/fake/staging/data.json")
        validate_staging_field_names(None, "/fake/staging/data.json")
        validate_staging_field_names("", "/fake/staging/data.json")

    def test_non_dict_records_pass(self):
        validate_staging_field_names(["plain string"], "/fake/staging/data.json")
        validate_staging_field_names("raw text", "/fake/staging/data.json")

    def test_error_message_includes_rename_suggestion(self):
        records = [{"source": "Architecture.md"}]
        with pytest.raises(ConfigValidationError, match="Rename"):
            validate_staging_field_names(records, "/fake/staging/data.json")

    def test_error_message_includes_filename(self):
        records = [{"source": "Architecture.md"}]
        with pytest.raises(ConfigValidationError, match="data.json"):
            validate_staging_field_names(records, "/fake/staging/data.json")
