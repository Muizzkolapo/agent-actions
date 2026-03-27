"""Tests for PreFlightErrorFormatter (agent_actions.validation.preflight.error_formatter)."""

from agent_actions.validation.preflight.error_formatter import (
    PreFlightErrorFormatter,
    ValidationIssue,
)

# ---------------------------------------------------------------------------
# ValidationIssue dataclass
# ---------------------------------------------------------------------------


class TestValidationIssue:
    """Test the ValidationIssue dataclass defaults and construction."""

    def test_defaults(self):
        issue = ValidationIssue(message="something broke")
        assert issue.message == "something broke"
        assert issue.issue_type == "error"
        assert issue.category == "general"
        assert issue.missing_refs == []
        assert issue.available_refs == []
        assert issue.hint is None
        assert issue.agent_name is None
        assert issue.location is None
        assert issue.extra_context == {}

    def test_custom_fields(self):
        issue = ValidationIssue(
            message="missing field",
            issue_type="warning",
            category="config",
            missing_refs=["field_a"],
            available_refs=["field_b", "field_c"],
            hint="Add field_a to config.",
            agent_name="my_agent",
            location="/path/to/config.yaml",
            extra_context={"key": "value"},
        )
        assert issue.issue_type == "warning"
        assert issue.category == "config"
        assert issue.missing_refs == ["field_a"]
        assert issue.available_refs == ["field_b", "field_c"]
        assert issue.hint == "Add field_a to config."
        assert issue.agent_name == "my_agent"
        assert issue.location == "/path/to/config.yaml"
        assert issue.extra_context == {"key": "value"}

    def test_mutable_defaults_are_independent(self):
        """Each instance should have its own list/dict, not shared defaults."""
        a = ValidationIssue(message="a")
        b = ValidationIssue(message="b")
        a.missing_refs.append("x")
        assert b.missing_refs == []
        a.extra_context["key"] = "val"
        assert b.extra_context == {}


# ---------------------------------------------------------------------------
# format_issue()
# ---------------------------------------------------------------------------


class TestFormatIssue:
    """Test formatting of a single ValidationIssue."""

    def test_error_label(self):
        issue = ValidationIssue(message="Bad config", issue_type="error")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "[ERROR] Bad config" in output

    def test_warning_label(self):
        issue = ValidationIssue(message="Deprecated field", issue_type="warning")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "[WARNING] Deprecated field" in output

    def test_missing_refs_displayed(self):
        issue = ValidationIssue(
            message="Missing paths",
            missing_refs=["/a/b", "/c/d"],
        )
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "Missing: /a/b, /c/d" in output

    def test_available_refs_displayed(self):
        issue = ValidationIssue(
            message="Unknown action",
            available_refs=["run", "validate", "deploy"],
        )
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "Available: run, validate, deploy" in output

    def test_available_refs_truncated_at_10(self):
        """More than 10 available refs should show '... (+N more)'."""
        refs = [f"ref_{i}" for i in range(15)]
        issue = ValidationIssue(message="Many refs", available_refs=refs)
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "... (+5 more)" in output
        # First 10 should be present
        assert "ref_0" in output
        assert "ref_9" in output
        # 11th should NOT be directly listed
        assert "ref_10" not in output.split("... (+5 more)")[0].split("Available:")[1]

    def test_available_refs_exactly_10(self):
        """Exactly 10 refs should not trigger truncation."""
        refs = [f"ref_{i}" for i in range(10)]
        issue = ValidationIssue(message="Ten refs", available_refs=refs)
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "more)" not in output
        assert "ref_9" in output

    def test_hint_displayed(self):
        issue = ValidationIssue(
            message="Problem found",
            hint="Try running with --force",
        )
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "Hint: Try running with --force" in output

    def test_no_hint_when_none(self):
        issue = ValidationIssue(message="No hint")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "Hint:" not in output

    def test_context_with_mode(self):
        issue = ValidationIssue(message="test")
        output = PreFlightErrorFormatter.format_issue(issue, mode="batch")
        assert "mode: batch" in output

    def test_context_unknown_mode_omitted(self):
        """When mode is 'unknown' it should not appear in context."""
        issue = ValidationIssue(message="test")
        output = PreFlightErrorFormatter.format_issue(issue, mode="unknown")
        assert "mode: unknown" not in output

    def test_context_with_agent_name(self):
        issue = ValidationIssue(message="test", agent_name="summarizer")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "agent: summarizer" in output

    def test_context_with_location(self):
        issue = ValidationIssue(message="test", location="config.yaml:12")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "location: config.yaml:12" in output

    def test_context_with_non_general_category(self):
        issue = ValidationIssue(message="test", category="vendor")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "category: vendor" in output

    def test_context_general_category_omitted(self):
        """The default 'general' category should not appear in context."""
        issue = ValidationIssue(message="test", category="general")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "category: general" not in output

    def test_no_context_section_when_all_defaults(self):
        """With all defaults and mode='unknown', no Context section should appear."""
        issue = ValidationIssue(message="test")
        output = PreFlightErrorFormatter.format_issue(issue, mode="unknown")
        assert "Context:" not in output

    def test_full_issue_format(self):
        """Comprehensive issue with all fields populated."""
        issue = ValidationIssue(
            message="Schema not found",
            issue_type="error",
            category="schema",
            missing_refs=["schema.json"],
            available_refs=["base.json", "extended.json"],
            hint="Check schema_file path in config.",
            agent_name="validator_agent",
            location="agent.yaml:5",
        )
        output = PreFlightErrorFormatter.format_issue(issue, mode="validate")
        assert "[ERROR] Schema not found" in output
        assert "Missing: schema.json" in output
        assert "Available: base.json, extended.json" in output
        assert "Hint: Check schema_file path in config." in output
        assert "mode: validate" in output
        assert "agent: validator_agent" in output
        assert "location: agent.yaml:5" in output
        assert "category: schema" in output

    def test_no_missing_or_available_refs(self):
        """When there are no refs at all, those lines should be absent."""
        issue = ValidationIssue(message="Simple error")
        output = PreFlightErrorFormatter.format_issue(issue)
        assert "Missing:" not in output
        assert "Available:" not in output


# ---------------------------------------------------------------------------
# format_issues()
# ---------------------------------------------------------------------------


class TestFormatIssues:
    """Test formatting of multiple ValidationIssues."""

    def test_empty_issues_returns_pass_message(self):
        output = PreFlightErrorFormatter.format_issues([])
        assert output == "Pre-flight validation passed with no issues."

    def test_single_error(self):
        issues = [ValidationIssue(message="Bad path", issue_type="error")]
        output = PreFlightErrorFormatter.format_issues(issues)
        assert "Pre-flight Validation Failed" in output
        assert "1 error(s), 0 warning(s)" in output
        assert "Errors:" in output
        assert "Bad path" in output
        assert "Warnings:" not in output

    def test_single_warning(self):
        issues = [ValidationIssue(message="Slow query", issue_type="warning")]
        output = PreFlightErrorFormatter.format_issues(issues)
        assert "Pre-flight Validation Failed" in output
        assert "0 error(s), 1 warning(s)" in output
        assert "Warnings:" in output
        assert "Slow query" in output

    def test_mixed_errors_and_warnings(self):
        issues = [
            ValidationIssue(message="Error 1", issue_type="error"),
            ValidationIssue(message="Error 2", issue_type="error"),
            ValidationIssue(message="Warning 1", issue_type="warning"),
        ]
        output = PreFlightErrorFormatter.format_issues(issues)
        assert "2 error(s), 1 warning(s)" in output
        assert "Errors:" in output
        assert "Warnings:" in output
        assert "Error 1" in output
        assert "Error 2" in output
        assert "Warning 1" in output

    def test_issues_are_numbered(self):
        issues = [
            ValidationIssue(message="First error", issue_type="error"),
            ValidationIssue(message="Second error", issue_type="error"),
        ]
        output = PreFlightErrorFormatter.format_issues(issues)
        assert "1. [ERROR] First error" in output
        assert "2. [ERROR] Second error" in output

    def test_mode_passed_to_format_issue(self):
        issues = [ValidationIssue(message="Test", issue_type="error")]
        output = PreFlightErrorFormatter.format_issues(issues, mode="batch")
        assert "mode: batch" in output

    def test_separator_lines_present(self):
        issues = [ValidationIssue(message="err", issue_type="error")]
        output = PreFlightErrorFormatter.format_issues(issues)
        assert "-" * 50 in output


# ---------------------------------------------------------------------------
# create_vendor_config_issue()
# ---------------------------------------------------------------------------


class TestCreateVendorConfigIssue:
    """Test the vendor config issue factory method."""

    def test_basic_creation(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="Invalid vendor config",
            vendor="openai",
        )
        assert issue.message == "Invalid vendor config"
        assert issue.issue_type == "error"
        assert issue.category == "vendor"
        assert issue.extra_context["vendor"] == "openai"

    def test_missing_fields_hint(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="Missing fields",
            vendor="anthropic",
            missing_fields=["api_key", "model"],
        )
        assert issue.missing_refs == ["api_key", "model"]
        assert "Add required fields: api_key, model" in issue.hint

    def test_unsupported_features_hint(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="Unsupported features",
            vendor="openai",
            unsupported_features=["streaming", "vision"],
        )
        assert "Remove unsupported features: streaming, vision" in issue.hint
        assert issue.extra_context["unsupported_features"] == ["streaming", "vision"]

    def test_both_missing_and_unsupported(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="Config problems",
            vendor="openai",
            missing_fields=["api_key"],
            unsupported_features=["streaming"],
        )
        assert "Add required fields: api_key" in issue.hint
        assert "Remove unsupported features: streaming" in issue.hint

    def test_no_hint_when_no_fields_or_features(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="Generic problem",
            vendor="openai",
        )
        assert issue.hint is None

    def test_agent_name_propagated(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="test",
            vendor="openai",
            agent_name="my_agent",
        )
        assert issue.agent_name == "my_agent"

    def test_missing_fields_none_defaults_to_empty_refs(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="test",
            vendor="openai",
            missing_fields=None,
        )
        assert issue.missing_refs == []

    def test_unsupported_features_none_defaults_to_empty(self):
        issue = PreFlightErrorFormatter.create_vendor_config_issue(
            message="test",
            vendor="openai",
            unsupported_features=None,
        )
        assert issue.extra_context["unsupported_features"] == []


# ---------------------------------------------------------------------------
# create_path_issue()
# ---------------------------------------------------------------------------


class TestCreatePathIssue:
    """Test the path issue factory method."""

    def test_basic_creation(self):
        issue = PreFlightErrorFormatter.create_path_issue(
            message="Paths not found",
            invalid_paths=["/a/b", "/c/d"],
        )
        assert issue.message == "Paths not found"
        assert issue.issue_type == "error"
        assert issue.category == "path"
        assert issue.missing_refs == ["/a/b", "/c/d"]

    def test_hint_contains_paths(self):
        issue = PreFlightErrorFormatter.create_path_issue(
            message="test",
            invalid_paths=["/missing/file.txt"],
            path_type="file",
        )
        assert "Verify these file(s) exist" in issue.hint
        assert "/missing/file.txt" in issue.hint

    def test_path_type_in_hint_and_context(self):
        issue = PreFlightErrorFormatter.create_path_issue(
            message="test",
            invalid_paths=["/dir"],
            path_type="directory",
        )
        assert "directory(s) exist" in issue.hint
        assert issue.extra_context["path_type"] == "directory"

    def test_agent_name_propagated(self):
        issue = PreFlightErrorFormatter.create_path_issue(
            message="test",
            invalid_paths=["/x"],
            agent_name="path_agent",
        )
        assert issue.agent_name == "path_agent"

    def test_default_path_type_is_file(self):
        issue = PreFlightErrorFormatter.create_path_issue(
            message="test",
            invalid_paths=["/x"],
        )
        assert issue.extra_context["path_type"] == "file"
        assert "file(s) exist" in issue.hint

    def test_multiple_invalid_paths_in_hint(self):
        paths = ["/a", "/b", "/c"]
        issue = PreFlightErrorFormatter.create_path_issue(
            message="test",
            invalid_paths=paths,
        )
        for p in paths:
            assert p in issue.hint
