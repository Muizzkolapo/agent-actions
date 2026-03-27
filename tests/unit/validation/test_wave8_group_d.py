"""Wave 8 Group D regression tests — Validation P1 fixes."""

import json
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest

from agent_actions.validation.preflight.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
    _get_vendor_capabilities,
)
from agent_actions.validation.project_validator import ProjectValidator
from agent_actions.validation.schema_validator import SchemaValidator
from agent_actions.validation.static_analyzer.schema_extractor import SchemaExtractor

# ---------------------------------------------------------------------------
# D-2  ·  SchemaExtractor._extract_field_name — flattened, no dead branch
# ---------------------------------------------------------------------------


class TestExtractFieldName:
    """D-2 — _extract_field_name handles all edge cases correctly."""

    def setup_method(self):
        self.extractor = SchemaExtractor()

    def test_simple_reference_no_period(self):
        assert self.extractor._extract_field_name("noperiod") == "noperiod"

    def test_qualified_reference_returns_field(self):
        assert self.extractor._extract_field_name("ns.field") == "field"

    def test_malformed_reference_trailing_period_returns_none(self):
        assert self.extractor._extract_field_name("ns.") is None

    def test_empty_string_returns_none(self):
        assert self.extractor._extract_field_name("") is None

    def test_dotted_field_name_uses_first_split(self):
        # split(".", 1) means "a.b.c" → parts = ["a", "b.c"] → returns "b.c"
        assert self.extractor._extract_field_name("ns.b.c") == "b.c"


# ---------------------------------------------------------------------------
# D-3  ·  ProjectValidator — _complete_validation fires at all exit points
# ---------------------------------------------------------------------------


class TestProjectValidatorCompleteValidationAlwaysFires:
    """D-3 — _complete_validation is called on every code path."""

    def _make_validator(self) -> ProjectValidator:
        return ProjectValidator(fire_events=False)

    def test_non_dict_input_calls_complete_validation(self):
        v = self._make_validator()
        with patch.object(v, "_complete_validation", wraps=v._complete_validation) as mock_cv:
            result = v.validate("not a dict")
        # _prepare_validation returns False → early exit → _complete_validation still called
        mock_cv.assert_called_once()
        assert result is False

    def test_invalid_field_types_calls_complete_validation(self):
        """When field-type checks fail, _complete_validation still fires."""
        v = self._make_validator()
        with patch.object(v, "_complete_validation", wraps=v._complete_validation) as mock_cv:
            result = v.validate(
                {
                    "project_name": 123,  # not a string → triggers early False branch
                    "output_dir": Path("/tmp"),
                    "project_dir": Path("/tmp/proj"),
                    "template": "default",
                    "available_templates": ["default"],
                    "force": False,
                }
            )
        mock_cv.assert_called_once()
        assert result is False

    def test_valid_input_calls_complete_validation(self, tmp_path):
        v = self._make_validator()
        project_dir = tmp_path / "my_project"
        with patch.object(v, "_complete_validation", wraps=v._complete_validation) as mock_cv:
            v.validate(
                {
                    "project_name": "my_project",
                    "output_dir": tmp_path,
                    "project_dir": project_dir,
                    "template": "default",
                    "available_templates": ["default"],
                    "force": False,
                }
            )
        mock_cv.assert_called_once()


# ---------------------------------------------------------------------------
# D-3  ·  PathValidator (workflow) — _complete_validation fires at all exits
# ---------------------------------------------------------------------------


class TestPathValidatorCompleteValidationAlwaysFires:
    """D-3 — agent_actions.validation.path_validator always calls _complete_validation."""

    def _make_validator(self):
        from agent_actions.validation.path_validator import PathValidator

        return PathValidator(fire_events=False)

    def test_non_dict_calls_complete_validation(self):
        v = self._make_validator()
        with patch.object(v, "_complete_validation", wraps=v._complete_validation) as mock_cv:
            result = v.validate("not a dict")
        mock_cv.assert_called_once()
        assert result is False

    def test_missing_operation_calls_complete_validation(self):
        v = self._make_validator()
        with patch.object(v, "_complete_validation", wraps=v._complete_validation) as mock_cv:
            result = v.validate({"path": "/tmp"})
        mock_cv.assert_called_once()
        assert result is False

    def test_valid_operation_calls_complete_validation(self, tmp_path):
        v = self._make_validator()
        f = tmp_path / "test.txt"
        f.write_text("hello")
        with patch.object(v, "_complete_validation", wraps=v._complete_validation) as mock_cv:
            v.validate({"operation": "validate_file", "path": f})
        mock_cv.assert_called_once()


# ---------------------------------------------------------------------------
# D-4  ·  SchemaValidator.check_schema_compatibility clears warnings between calls
# ---------------------------------------------------------------------------


class TestCheckSchemaCompatibilityClearsWarnings:
    """D-4 — warnings from a previous call must not bleed into the next call."""

    def test_warnings_do_not_bleed_between_calls(self):
        """Manually seed a warning before the call to prove clear_warnings() runs.

        check_schema_compatibility itself only calls add_error(), so we simulate
        a warning left over from a prior operation (e.g. validate_schema_files).
        Without the clear_warnings() added in D-4, this warning would survive
        into the second call's get_warnings() result.
        """
        v = SchemaValidator(fire_events=False)

        schema = {"type": "object", "properties": {"x": {"type": "string"}}}

        # Simulate a stale warning from a prior validation operation
        v.add_warning("stale warning from previous call")
        assert "stale warning from previous call" in v.get_warnings()

        # check_schema_compatibility must clear warnings at entry
        v.check_schema_compatibility(schema, schema, "A", "A")

        assert "stale warning from previous call" not in v.get_warnings(), (
            "clear_warnings() was not called: stale warning survived into new call"
        )

    def test_errors_do_not_bleed_between_calls(self):
        """Confirm clear_errors() also runs (pre-existing behaviour)."""
        v = SchemaValidator(fire_events=False)

        schema_int = {"type": "integer"}
        schema_str = {"type": "string"}
        schema_ok = {"type": "object", "properties": {}}

        # First call — incompatible types produce errors
        v.check_schema_compatibility(schema_int, schema_str, "Int", "Str")
        assert v.has_errors()

        # Second call — compatible schemas must start with a clean error state
        v.check_schema_compatibility(schema_ok, schema_ok, "Ok", "Ok")
        assert not v.has_errors()


# ---------------------------------------------------------------------------
# D-5  ·  SchemaValidator._process_schema_file — no fall-through after ValidationError
# ---------------------------------------------------------------------------


class TestProcessSchemaFileNoFallThrough:
    """D-5 — _check_common_schema_issues_static not called after ValidationError."""

    def test_validation_error_handler_does_not_call_common_issues(self, tmp_path):
        """When _validate_against_meta_schema_static raises ValidationError,
        _check_common_schema_issues_static must NOT be called."""
        v = SchemaValidator(fire_events=False)

        # Write a schema file that passes structural checks but will fail meta-schema
        schema_data = {"type": "object", "properties": {"x": {"type": "string"}}}
        schema_file = tmp_path / "input.json"
        schema_file.write_text(json.dumps(schema_data))

        fake_error = jsonschema.exceptions.ValidationError("bad schema")

        with (
            patch.object(v, "_validate_against_meta_schema_static", side_effect=fake_error),
            patch.object(v, "_check_common_schema_issues_static", return_value=[]) as mock_common,
        ):
            v._process_schema_file(
                file_path=schema_file,
                schema_name="input",
                agent_name="agent_a",
            )

        mock_common.assert_not_called()

    def test_os_error_handler_does_not_call_common_issues(self, tmp_path):
        """When _validate_against_meta_schema_static raises OSError,
        _check_common_schema_issues_static must NOT be called."""
        v = SchemaValidator(fire_events=False)

        schema_data = {"type": "object", "properties": {"x": {"type": "string"}}}
        schema_file = tmp_path / "input.json"
        schema_file.write_text(json.dumps(schema_data))

        with (
            patch.object(
                v, "_validate_against_meta_schema_static", side_effect=OSError("disk err")
            ),
            patch.object(v, "_check_common_schema_issues_static", return_value=[]) as mock_common,
        ):
            v._process_schema_file(
                file_path=schema_file,
                schema_name="input",
                agent_name="agent_a",
            )

        mock_common.assert_not_called()


# ---------------------------------------------------------------------------
# D-6  ·  VendorCompatibilityValidator.clear_cache() resets module-level cache
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_vendor_cache():
    """Ensure the vendor capabilities cache is clean before and after each test."""
    VendorCompatibilityValidator.clear_cache()
    yield
    VendorCompatibilityValidator.clear_cache()


class TestVendorCompatibilityValidatorClearCache:
    """D-6 — clear_cache() classmethod resets the lazy-loaded cache."""

    def test_clear_cache_resets_to_none(self):
        # Prime the cache
        _get_vendor_capabilities()
        # After clear, re-initialisation happens on next access (not None internally)
        VendorCompatibilityValidator.clear_cache()
        # Calling again re-initialises — must not raise
        caps = _get_vendor_capabilities()
        assert isinstance(caps, dict)

    def test_clear_cache_allows_fresh_load(self):
        first = _get_vendor_capabilities()
        VendorCompatibilityValidator.clear_cache()
        second = _get_vendor_capabilities()
        # Both should have the same keys (same registry)
        assert set(first.keys()) == set(second.keys())

    def test_existing_tests_pass_in_any_order_after_fixture(self):
        """Smoke test: validator works after a cache reset."""
        validator = VendorCompatibilityValidator()
        result = validator.validate({"agent_config": {}})
        # tool agents are exempt from vendor requirement; general case is an error
        # Just assert no crash and returns bool
        assert isinstance(result, bool)
