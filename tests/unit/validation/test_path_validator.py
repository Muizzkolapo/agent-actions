"""Tests for preflight PathValidator (agent_actions.validation.preflight.path_validator)."""

import os
from unittest.mock import patch

import pytest

from agent_actions.validation.preflight.error_formatter import ValidationIssue
from agent_actions.validation.preflight.path_validator import PathValidator


@pytest.fixture
def validator():
    """Create a PathValidator with events disabled via patching."""
    with patch("agent_actions.validation.base_validator.fire_event"):
        v = PathValidator()
        v._fire_events = False
        yield v


# ---------------------------------------------------------------------------
# validate() — basic dispatch and data validation
# ---------------------------------------------------------------------------


class TestValidateBasic:
    """Test top-level validate() with edge-case inputs."""

    def test_non_dict_data_returns_false(self, validator):
        """Non-dict data should fail _prepare_validation."""
        result = validator.validate("not a dict")
        assert result is False
        assert validator.has_errors()

    def test_empty_dict_returns_true(self, validator):
        """Empty dict with no paths key should pass (no paths to validate)."""
        result = validator.validate({})
        assert result is True
        assert not validator.has_errors()

    def test_empty_paths_list_returns_true(self, validator):
        """An explicit empty paths list should pass."""
        result = validator.validate({"paths": []})
        assert result is True
        assert not validator.has_errors()

    def test_none_data_returns_false(self, validator):
        """None data should fail as it's not a dict."""
        result = validator.validate(None)
        assert result is False

    def test_issues_reset_between_calls(self, validator, tmp_path):
        """Issues list should be cleared on each validate() call."""
        # First call with a nonexistent path to generate issues
        validator.validate({"paths": ["/nonexistent/path/abc123"]})
        assert validator.get_issues() or validator.has_errors()

        # Second call with valid data should reset
        validator.validate({"paths": []})
        assert validator.get_issues() == []
        assert not validator.has_errors()


# ---------------------------------------------------------------------------
# validate() — file path validation
# ---------------------------------------------------------------------------


class TestValidateFilePaths:
    """Test file path validation through validate()."""

    def test_valid_file(self, validator, tmp_path):
        """Existing file should pass validation."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        result = validator.validate({"paths": [str(f)], "path_type": "file"})
        assert result is True
        assert not validator.has_errors()

    def test_nonexistent_file_strict(self, validator):
        """Nonexistent path in strict mode should produce an error."""
        result = validator.validate(
            {"paths": ["/no/such/file.txt"], "path_type": "file"},
            config={"strict": True},
        )
        assert result is False
        errors = validator.get_errors()
        assert any("does not exist" in e for e in errors)

    def test_nonexistent_file_non_strict(self, validator):
        """Nonexistent path in non-strict mode should produce a warning, not error."""
        result = validator.validate(
            {"paths": ["/no/such/file.txt"], "path_type": "file"},
            config={"strict": False},
        )
        # Non-strict: warning only, but issues are still created for invalid paths.
        # The validate still returns True (no errors), but warnings exist.
        assert result is True
        warnings = validator.get_warnings()
        assert any("does not exist" in w for w in warnings)

    def test_directory_when_file_expected(self, validator, tmp_path):
        """A directory path should fail when path_type is 'file'."""
        result = validator.validate(
            {"paths": [str(tmp_path)], "path_type": "file"}
        )
        assert result is False
        assert any("not a file" in e for e in validator.get_errors())

    def test_file_when_directory_expected(self, validator, tmp_path):
        """A file path should fail when path_type is 'directory'."""
        f = tmp_path / "file.txt"
        f.write_text("data")
        result = validator.validate(
            {"paths": [str(f)], "path_type": "directory"}
        )
        assert result is False
        assert any("not a directory" in e for e in validator.get_errors())

    def test_empty_string_path_is_skipped(self, validator):
        """Empty string paths should be skipped silently."""
        result = validator.validate({"paths": ["", ""], "path_type": "file"})
        assert result is True
        assert not validator.has_errors()

    def test_multiple_paths_mixed_validity(self, validator, tmp_path):
        """Mix of valid and invalid paths should fail overall."""
        valid = tmp_path / "good.txt"
        valid.write_text("ok")
        result = validator.validate(
            {"paths": [str(valid), "/no/exist.txt"], "path_type": "file"}
        )
        assert result is False


# ---------------------------------------------------------------------------
# validate() — path_type variations
# ---------------------------------------------------------------------------


class TestPathTypes:
    """Test all supported path_type values."""

    @pytest.mark.parametrize("path_type", ["file", "input", "schema", "prompt"])
    def test_file_like_path_types_valid(self, validator, tmp_path, path_type):
        """All file-like path types should accept a real file."""
        f = tmp_path / "test.txt"
        f.write_text("ok")
        result = validator.validate(
            {"paths": [str(f)], "path_type": path_type}
        )
        assert result is True

    @pytest.mark.parametrize("path_type", ["file", "input", "schema", "prompt"])
    def test_file_like_path_types_reject_dir(self, validator, tmp_path, path_type):
        """All file-like path types should reject a directory."""
        result = validator.validate(
            {"paths": [str(tmp_path)], "path_type": path_type}
        )
        assert result is False
        assert any("not a file" in e for e in validator.get_errors())

    @pytest.mark.parametrize("path_type", ["directory", "output"])
    def test_directory_like_path_types_valid(self, validator, tmp_path, path_type):
        """Directory-like path types should accept a real directory."""
        result = validator.validate(
            {"paths": [str(tmp_path)], "path_type": path_type}
        )
        assert result is True

    @pytest.mark.parametrize("path_type", ["directory", "output"])
    def test_directory_like_path_types_reject_file(self, validator, tmp_path, path_type):
        """Directory-like path types should reject a file."""
        f = tmp_path / "file.txt"
        f.write_text("data")
        result = validator.validate(
            {"paths": [str(f)], "path_type": path_type}
        )
        assert result is False
        assert any("not a directory" in e for e in validator.get_errors())


# ---------------------------------------------------------------------------
# validate() — permission checks
# ---------------------------------------------------------------------------


class TestPermissionChecks:
    """Test readable/writable permission checks."""

    def test_readable_file(self, validator, tmp_path):
        """A normal file should pass readable check."""
        f = tmp_path / "read.txt"
        f.write_text("readable")
        result = validator.validate(
            {"paths": [str(f)], "path_type": "file", "check_readable": True}
        )
        assert result is True

    def test_not_readable_file(self, validator, tmp_path):
        """A file without read permission should fail readable check."""
        f = tmp_path / "noread.txt"
        f.write_text("secret")
        with patch("agent_actions.validation.preflight.path_validator.os.access") as mock_access:
            # os.access is called for R_OK and possibly W_OK; fail on R_OK
            def side_effect(path, mode):
                if mode == os.R_OK:
                    return False
                return True

            mock_access.side_effect = side_effect
            result = validator.validate(
                {"paths": [str(f)], "path_type": "file", "check_readable": True}
            )
        assert result is False
        assert any("not readable" in e for e in validator.get_errors())

    def test_writable_file(self, validator, tmp_path):
        """A normal file should pass writable check."""
        f = tmp_path / "write.txt"
        f.write_text("writable")
        result = validator.validate(
            {
                "paths": [str(f)],
                "path_type": "file",
                "check_readable": False,
                "check_writable": True,
            }
        )
        assert result is True

    def test_not_writable_file(self, validator, tmp_path):
        """A file without write permission should fail writable check."""
        f = tmp_path / "nowrite.txt"
        f.write_text("locked")
        with patch("agent_actions.validation.preflight.path_validator.os.access") as mock_access:
            def side_effect(path, mode):
                if mode == os.W_OK:
                    return False
                return True

            mock_access.side_effect = side_effect
            result = validator.validate(
                {
                    "paths": [str(f)],
                    "path_type": "file",
                    "check_readable": False,
                    "check_writable": True,
                }
            )
        assert result is False
        assert any("not writable" in e for e in validator.get_errors())

    def test_both_readable_and_writable_failure(self, validator, tmp_path):
        """When both read and write checks fail, both errors are recorded."""
        f = tmp_path / "locked.txt"
        f.write_text("locked")
        with patch("agent_actions.validation.preflight.path_validator.os.access", return_value=False):
            result = validator.validate(
                {
                    "paths": [str(f)],
                    "path_type": "file",
                    "check_readable": True,
                    "check_writable": True,
                }
            )
        assert result is False
        errors = validator.get_errors()
        assert any("not readable" in e for e in errors)
        assert any("not writable" in e for e in errors)


# ---------------------------------------------------------------------------
# validate() — issues tracking
# ---------------------------------------------------------------------------


class TestIssuesTracking:
    """Test that ValidationIssues are correctly created."""

    def test_invalid_paths_create_path_issue(self, validator):
        """Nonexistent paths should produce a ValidationIssue via create_path_issue."""
        validator.validate({"paths": ["/no/exist1", "/no/exist2"], "path_type": "file"})
        issues = validator.get_issues()
        assert len(issues) >= 1
        path_issues = [i for i in issues if i.category == "path"]
        assert len(path_issues) >= 1
        assert "2 path(s)" in path_issues[0].message

    def test_permission_errors_create_issue(self, validator, tmp_path):
        """Permission failures should create a permission-related issue."""
        f = tmp_path / "noperm.txt"
        f.write_text("x")
        with patch("agent_actions.validation.preflight.path_validator.os.access", return_value=False):
            validator.validate(
                {
                    "paths": [str(f)],
                    "path_type": "file",
                    "check_readable": True,
                }
            )
        issues = validator.get_issues()
        perm_issues = [i for i in issues if "Permission" in i.message]
        assert len(perm_issues) == 1
        assert perm_issues[0].issue_type == "error"
        assert "Check file permissions" in perm_issues[0].hint

    def test_agent_name_propagated_to_issues(self, validator):
        """The agent_name from config should appear in issues."""
        validator.validate(
            {"paths": ["/no/exist"], "path_type": "file"},
            config={"agent_name": "my_agent"},
        )
        issues = validator.get_issues()
        assert any(i.agent_name == "my_agent" for i in issues)

    def test_no_issues_for_valid_paths(self, validator, tmp_path):
        """Valid paths should produce no issues."""
        f = tmp_path / "ok.txt"
        f.write_text("ok")
        validator.validate({"paths": [str(f)], "path_type": "file"})
        assert validator.get_issues() == []


# ---------------------------------------------------------------------------
# validate_paths() — convenience wrapper
# ---------------------------------------------------------------------------


class TestValidatePaths:
    """Test the validate_paths() convenience method."""

    def test_valid_paths(self, validator, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("a")
        result = validator.validate_paths([str(f)], path_type="file")
        assert result is True

    def test_invalid_paths(self, validator):
        result = validator.validate_paths(["/nonexistent"], path_type="file")
        assert result is False

    def test_agent_name_passed_through(self, validator):
        validator.validate_paths(
            ["/nonexistent"], path_type="file", agent_name="test_agent"
        )
        issues = validator.get_issues()
        assert any(i.agent_name == "test_agent" for i in issues)

    def test_writable_check(self, validator, tmp_path):
        f = tmp_path / "w.txt"
        f.write_text("w")
        result = validator.validate_paths(
            [str(f)], path_type="file", check_writable=True, check_readable=False
        )
        assert result is True


# ---------------------------------------------------------------------------
# validate_agent_paths() — agent config path extraction
# ---------------------------------------------------------------------------


class TestValidateAgentPaths:
    """Test validate_agent_paths() with various agent config shapes."""

    def test_empty_config(self, validator):
        """Empty config has nothing to validate; should pass."""
        result = validator.validate_agent_paths({})
        assert result is True

    def test_valid_input_file(self, validator, tmp_path):
        f = tmp_path / "input.json"
        f.write_text("{}")
        result = validator.validate_agent_paths({"input_file": str(f)})
        assert result is True

    def test_invalid_input_file(self, validator):
        result = validator.validate_agent_paths({"input_file": "/no/file.json"})
        assert result is False

    def test_valid_output_path(self, validator, tmp_path):
        """Output paths check writable, not readable."""
        result = validator.validate_agent_paths({"output_path": str(tmp_path)})
        assert result is True

    def test_schema_file(self, validator, tmp_path):
        f = tmp_path / "schema.json"
        f.write_text("{}")
        result = validator.validate_agent_paths({"schema_file": str(f)})
        assert result is True

    def test_prompt_file(self, validator, tmp_path):
        f = tmp_path / "prompt.txt"
        f.write_text("You are a helpful assistant.")
        result = validator.validate_agent_paths({"prompt_file": str(f)})
        assert result is True

    def test_tools_path(self, validator, tmp_path):
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        result = validator.validate_agent_paths({"tools_path": str(tools_dir)})
        assert result is True

    def test_all_path_keys(self, validator, tmp_path):
        """Config with all recognized path keys should validate all of them."""
        inp = tmp_path / "input.json"
        inp.write_text("{}")
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        schema = tmp_path / "schema.json"
        schema.write_text("{}")
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("prompt")
        tools = tmp_path / "tools"
        tools.mkdir()

        result = validator.validate_agent_paths(
            {
                "input_file": str(inp),
                "output_path": str(out_dir),
                "schema_file": str(schema),
                "prompt_file": str(prompt),
                "tools_path": str(tools),
            },
            agent_name="full_agent",
        )
        assert result is True

    def test_multiple_invalid_paths(self, validator):
        """Multiple invalid paths should all be caught."""
        result = validator.validate_agent_paths(
            {
                "input_file": "/no/input.json",
                "schema_file": "/no/schema.json",
            }
        )
        assert result is False

    def test_agent_name_propagated(self, validator):
        """Agent name should be propagated to validation calls."""
        validator.validate_agent_paths(
            {"input_file": "/no/file"}, agent_name="agent_x"
        )
        issues = validator.get_issues()
        assert any(i.agent_name == "agent_x" for i in issues)

    def test_input_path_key(self, validator, tmp_path):
        """input_path key should be recognized as an input path."""
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        result = validator.validate_agent_paths({"input_path": str(f)})
        assert result is True

    def test_source_path_key(self, validator, tmp_path):
        """source_path key should be recognized as an input path."""
        f = tmp_path / "source.py"
        f.write_text("x = 1")
        result = validator.validate_agent_paths({"source_path": str(f)})
        assert result is True

    def test_output_file_key_with_directory(self, validator, tmp_path):
        """output_file maps to path_type='output' which expects a directory."""
        out_dir = tmp_path / "output_dir"
        out_dir.mkdir()
        result = validator.validate_agent_paths({"output_file": str(out_dir)})
        assert result is True

    def test_output_file_key_with_file_fails(self, validator, tmp_path):
        """output_file with path_type='output' rejects a regular file (expects dir)."""
        f = tmp_path / "out.json"
        f.write_text("{}")
        result = validator.validate_agent_paths({"output_file": str(f)})
        assert result is False


# ---------------------------------------------------------------------------
# get_issues()
# ---------------------------------------------------------------------------


class TestGetIssues:
    """Test get_issues() returns correct issue objects."""

    def test_returns_list(self, validator):
        assert isinstance(validator.get_issues(), list)

    def test_returns_validation_issue_objects(self, validator):
        validator.validate({"paths": ["/nope"], "path_type": "file"})
        for issue in validator.get_issues():
            assert isinstance(issue, ValidationIssue)
