"""Tests for PathValidator to improve coverage."""

from pathlib import Path

import pytest

from agent_actions.validation.path_validator import PathValidationOptions, PathValidator


@pytest.fixture
def validator():
    """Create a PathValidator with events disabled."""
    return PathValidator(fire_events=False)


# ---------------------------------------------------------------------------
# PathValidationOptions defaults
# ---------------------------------------------------------------------------


class TestPathValidationOptions:
    """Test dataclass defaults."""

    def test_defaults(self):
        opts = PathValidationOptions()
        assert opts.required is True
        assert opts.must_be_readable is True
        assert opts.must_be_writable is False
        assert opts.must_be_executable is False

    def test_custom(self):
        opts = PathValidationOptions(
            required=False,
            must_be_readable=False,
            must_be_writable=True,
            must_be_executable=True,
        )
        assert opts.required is False
        assert opts.must_be_writable is True


# ---------------------------------------------------------------------------
# validate() dispatch
# ---------------------------------------------------------------------------


class TestValidateDispatch:
    """Test the top-level validate() routing."""

    def test_non_dict_data(self, validator):
        result = validator.validate("not a dict")
        assert result is False

    def test_missing_operation(self, validator):
        result = validator.validate({"path": "/tmp"})
        assert result is False
        assert any("operation not specified" in e.lower() for e in validator.get_errors())

    def test_unknown_operation(self, validator):
        result = validator.validate({"operation": "unknown_op", "path": Path("/tmp")})
        assert result is False
        assert any("unknown operation" in e.lower() for e in validator.get_errors())

    def test_missing_path_for_file_operation(self, validator):
        result = validator.validate({"operation": "validate_file"})
        assert result is False
        assert any("'path'" in e for e in validator.get_errors())


# ---------------------------------------------------------------------------
# validate_file
# ---------------------------------------------------------------------------


class TestValidateFile:
    """Test file validation via validate()."""

    def test_valid_file(self, validator, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = validator.validate({"operation": "validate_file", "path": f})
        assert result is True

    def test_nonexistent_file(self, validator, tmp_path):
        result = validator.validate({"operation": "validate_file", "path": tmp_path / "nope.txt"})
        assert result is False
        assert any("does not exist" in e for e in validator.get_errors())

    def test_path_is_directory_not_file(self, validator, tmp_path):
        result = validator.validate({"operation": "validate_file", "path": tmp_path})
        assert result is False
        assert any("not a file" in e for e in validator.get_errors())

    def test_file_with_string_path(self, validator, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        result = validator.validate({"operation": "validate_file", "path": str(f)})
        assert result is True

    def test_not_required_and_missing(self, validator, tmp_path):
        result = validator.validate(
            {
                "operation": "validate_file",
                "path": tmp_path / "optional.txt",
                "required": False,
            }
        )
        assert result is True

    def test_custom_path_name(self, validator, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("ok")
        result = validator.validate(
            {
                "operation": "validate_file",
                "path": f,
                "path_name": "my_config_file",
            }
        )
        assert result is True


# ---------------------------------------------------------------------------
# validate_directory
# ---------------------------------------------------------------------------


class TestValidateDirectory:
    """Test directory validation via validate()."""

    def test_valid_directory(self, validator, tmp_path):
        result = validator.validate({"operation": "validate_directory", "path": tmp_path})
        assert result is True

    def test_nonexistent_directory(self, validator, tmp_path):
        result = validator.validate(
            {"operation": "validate_directory", "path": tmp_path / "missing"}
        )
        assert result is False

    def test_path_is_file_not_directory(self, validator, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = validator.validate({"operation": "validate_directory", "path": f})
        assert result is False
        assert any("not a directory" in e for e in validator.get_errors())

    def test_writable_check(self, validator, tmp_path):
        result = validator.validate(
            {
                "operation": "validate_directory",
                "path": tmp_path,
                "must_be_writable": True,
            }
        )
        assert result is True


# ---------------------------------------------------------------------------
# ensure_directory_exists
# ---------------------------------------------------------------------------


class TestEnsureDirectoryExists:
    """Test ensure_directory_exists via validate()."""

    def test_create_missing_directory(self, validator, tmp_path):
        new_dir = tmp_path / "new_subdir"
        result = validator.validate({"operation": "ensure_directory_exists", "path": new_dir})
        assert result is True
        assert new_dir.is_dir()

    def test_existing_directory(self, validator, tmp_path):
        result = validator.validate({"operation": "ensure_directory_exists", "path": tmp_path})
        assert result is True

    def test_do_not_create_missing(self, validator, tmp_path):
        missing = tmp_path / "no_create"
        result = validator.validate(
            {
                "operation": "ensure_directory_exists",
                "path": missing,
                "create_if_missing": False,
            }
        )
        assert result is False
        assert any("creation not enabled" in e.lower() for e in validator.get_errors())

    def test_path_exists_but_is_file(self, validator, tmp_path):
        f = tmp_path / "afile"
        f.write_text("data")
        result = validator.validate({"operation": "ensure_directory_exists", "path": f})
        assert result is False
        assert any("not a directory" in e for e in validator.get_errors())


# ---------------------------------------------------------------------------
# validate_user_code_path
# ---------------------------------------------------------------------------


class TestValidateUserCodePath:
    """Test user code path validation via validate()."""

    def test_none_path_is_valid(self, validator):
        result = validator.validate({"operation": "validate_user_code_path", "path": None})
        assert result is True

    def test_valid_directory(self, validator, tmp_path):
        result = validator.validate({"operation": "validate_user_code_path", "path": str(tmp_path)})
        assert result is True

    def test_nonexistent_path(self, validator, tmp_path):
        result = validator.validate(
            {"operation": "validate_user_code_path", "path": str(tmp_path / "nope")}
        )
        assert result is False

    def test_path_is_file(self, validator, tmp_path):
        f = tmp_path / "file.py"
        f.write_text("x = 1")
        result = validator.validate({"operation": "validate_user_code_path", "path": str(f)})
        assert result is False
        assert any("not a directory" in e for e in validator.get_errors())

    def test_non_string_path_error(self, validator):
        result = validator.validate({"operation": "validate_user_code_path", "path": 12345})
        assert result is False
        assert any("string or None" in e for e in validator.get_errors())

    def test_empty_string_path_valid(self, validator):
        """Empty string is falsy, so treated like None (not provided)."""
        result = validator.validate({"operation": "validate_user_code_path", "path": ""})
        assert result is True


# ---------------------------------------------------------------------------
# _validate_path_entity_logic (edge cases)
# ---------------------------------------------------------------------------


class TestValidatePathEntityLogic:
    """Test internal path entity logic directly."""

    def test_unknown_entity_type(self, validator, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        validator._validate_path_entity_logic(
            f, "something_else", "test_entity", PathValidationOptions()
        )
        assert validator.has_errors()
        assert any("unknown entity type" in e.lower() for e in validator.get_errors())

    def test_writable_check_on_file(self, validator, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        opts = PathValidationOptions(must_be_writable=True)
        validator._validate_path_entity_logic(f, "file", "test_file", opts)
        # On normal tmp_path, file should be writable
        assert not validator.has_errors()

    def test_executable_check(self, validator, tmp_path):
        f = tmp_path / "script.sh"
        f.write_text("#!/bin/bash\necho hi")
        opts = PathValidationOptions(must_be_executable=True)
        validator._validate_path_entity_logic(f, "file", "script", opts)
        # Script is not executable by default
        assert validator.has_errors()
        assert any("not executable" in e for e in validator.get_errors())


# ---------------------------------------------------------------------------
# _ensure_directory_exists_logic (edge cases)
# ---------------------------------------------------------------------------


class TestEnsureDirectoryExistsLogic:
    """Test internal directory ensure logic."""

    def test_create_nested_directories(self, validator, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        validator._ensure_directory_exists_logic(
            nested, "nested_dir", create_if_missing=True, must_be_writable_after_creation=True
        )
        assert not validator.has_errors()
        assert nested.is_dir()

    def test_existing_writable_dir(self, validator, tmp_path):
        validator._ensure_directory_exists_logic(
            tmp_path, "output", create_if_missing=False, must_be_writable_after_creation=True
        )
        assert not validator.has_errors()
