"""Snapshot-style tests for format_user_message output."""

from agent_actions.errors.preflight import PreFlightValidationError
from agent_actions.errors.validation import SchemaValidationError


class TestPreFlightValidationErrorFormat:
    """Tests for PreFlightValidationError.format_user_message()."""

    def test_full_message(self):
        err = PreFlightValidationError(
            "Invalid context references",
            missing_references=["ref_a", "ref_b"],
            available_references=["ctx_x", "ctx_y"],
            hint="Check your context references",
            agent_name="my_agent",
            mode="batch",
        )
        expected = (
            "Invalid context references\n"
            "\n"
            "  Missing: ref_a, ref_b\n"
            "  Available: ctx_x, ctx_y\n"
            "\n"
            "  Hint: Check your context references\n"
            "\n"
            "  Agent: my_agent\n"
            "  Mode: batch"
        )
        assert err.format_user_message() == expected

    def test_missing_only(self):
        err = PreFlightValidationError(
            "Bad refs",
            missing_references=["x"],
        )
        expected = "Bad refs\n\n  Missing: x"
        assert err.format_user_message() == expected

    def test_hint_only(self):
        err = PreFlightValidationError(
            "Problem",
            hint="Try this",
        )
        expected = "Problem\n\n  Hint: Try this"
        assert err.format_user_message() == expected

    def test_truncation_at_10(self):
        refs = [f"ref_{i}" for i in range(15)]
        err = PreFlightValidationError(
            "Too many",
            available_references=refs,
        )
        msg = err.format_user_message()
        assert "(+5 more)" in msg
        assert "ref_10" not in msg

    def test_str_delegates_to_format(self):
        err = PreFlightValidationError("msg", hint="h")
        assert str(err) == err.format_user_message()


class TestSchemaValidationErrorFormat:
    """Tests for SchemaValidationError.format_user_message()."""

    def test_full_message(self):
        err = SchemaValidationError(
            "Schema validation failed",
            schema_name="output_schema",
            action_name="process_data",
            validation_type="output",
            missing_fields=["field_a"],
            extra_fields=["field_z"],
            type_errors={"field_b": ("str", "int")},
            error_path="root.items[0]",
            hint="Check field types",
        )
        expected = (
            "Schema validation failed\n"
            "\n"
            "  Schema: output_schema\n"
            "  Action: process_data\n"
            "  Validation: output\n"
            "\n"
            "  Missing fields: field_a\n"
            "  Extra fields: field_z\n"
            "\n"
            "  Type mismatches:\n"
            "    - field_b: expected str, got int\n"
            "\n"
            "  Error path: root.items[0]\n"
            "\n"
            "  Hint: Check field types"
        )
        assert err.format_user_message() == expected

    def test_schema_name_only(self):
        err = SchemaValidationError(
            "Failed",
            schema_name="my_schema",
        )
        expected = "Failed\n\n  Schema: my_schema"
        assert err.format_user_message() == expected

    def test_missing_and_extra_fields(self):
        err = SchemaValidationError(
            "Mismatch",
            missing_fields=["a", "b"],
            extra_fields=["z"],
        )
        expected = "Mismatch\n\n  Missing fields: a, b\n  Extra fields: z"
        assert err.format_user_message() == expected

    def test_type_errors_only(self):
        err = SchemaValidationError(
            "Type problem",
            type_errors={"name": ("str", "int"), "age": ("int", "str")},
        )
        expected = (
            "Type problem\n"
            "\n"
            "  Type mismatches:\n"
            "    - name: expected str, got int\n"
            "    - age: expected int, got str"
        )
        assert err.format_user_message() == expected

    def test_hint_only(self):
        err = SchemaValidationError(
            "Bad",
            hint="Fix it",
        )
        expected = "Bad\n\n  Hint: Fix it"
        assert err.format_user_message() == expected

    def test_str_delegates_to_format(self):
        err = SchemaValidationError("msg", hint="h")
        assert str(err) == err.format_user_message()
