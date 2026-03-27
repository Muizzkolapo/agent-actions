"""Tests for PromptValidator to improve coverage."""

import pytest

from agent_actions.validation.prompt_validator import PromptValidator


@pytest.fixture
def validator():
    """Create a PromptValidator with events disabled."""
    return PromptValidator(fire_events=False)


# ---------------------------------------------------------------------------
# Static helpers
# ---------------------------------------------------------------------------


class TestFindPromptSections:
    """Test section heading extraction."""

    def test_finds_sections(self):
        content = "# Section 1\nsome text\n## Section 2\nmore text"
        sections = PromptValidator._find_prompt_sections_in_content(content)
        assert sections == ["Section 1", "Section 2"]

    def test_no_sections(self):
        content = "Just plain text without headings."
        assert PromptValidator._find_prompt_sections_in_content(content) == []

    def test_empty_content(self):
        assert PromptValidator._find_prompt_sections_in_content("") == []


class TestFindPromptIds:
    """Test prompt ID extraction from {prompt ID} tokens."""

    def test_finds_ids(self):
        content = "{prompt analyze}\nDo something\n{end_prompt}\n{prompt summarize}\nDo more\n{end_prompt}"
        ids = PromptValidator._find_prompt_ids_in_content(content)
        assert ids == ["analyze", "summarize"]

    def test_no_ids(self):
        content = "```python\ncode here\n```"
        assert PromptValidator._find_prompt_ids_in_content(content) == []

    def test_empty_content(self):
        assert PromptValidator._find_prompt_ids_in_content("") == []


class TestFindDuplicateIds:
    """Test duplicate ID detection."""

    def test_no_duplicates(self):
        assert PromptValidator._find_duplicate_ids_in_list(["a", "b", "c"]) == set()

    def test_has_duplicates(self):
        assert PromptValidator._find_duplicate_ids_in_list(["a", "b", "a"]) == {"a"}

    def test_empty_list(self):
        assert PromptValidator._find_duplicate_ids_in_list([]) == set()

    def test_all_same(self):
        assert PromptValidator._find_duplicate_ids_in_list(["x", "x", "x"]) == {"x"}


# ---------------------------------------------------------------------------
# _check_prompt_file_size
# ---------------------------------------------------------------------------


class TestCheckPromptFileSize:
    """Test file size limit enforcement."""

    def test_small_file_ok(self, validator, tmp_path):
        f = tmp_path / "small.md"
        f.write_text("hello")
        assert validator._check_prompt_file_size(f) is True
        assert not validator.has_errors()

    def test_oversized_file(self, validator, tmp_path):
        f = tmp_path / "large.md"
        # Write content exceeding default max (100KB)
        f.write_text("x" * (101 * 1024))
        assert validator._check_prompt_file_size(f) is False
        assert validator.has_errors()
        assert any("exceeds maximum size" in e for e in validator.get_errors())


# ---------------------------------------------------------------------------
# _read_prompt_file
# ---------------------------------------------------------------------------


class TestReadPromptFile:
    """Test file reading with error handling."""

    def test_valid_file(self, validator, tmp_path):
        f = tmp_path / "prompt.md"
        f.write_text("content here")
        result = validator._read_prompt_file(f)
        assert result == "content here"

    def test_missing_file(self, validator, tmp_path):
        f = tmp_path / "missing.md"
        result = validator._read_prompt_file(f)
        assert result is None
        assert validator.has_errors()


# ---------------------------------------------------------------------------
# _check_prompt_id_duplicates
# ---------------------------------------------------------------------------


class TestCheckPromptIdDuplicates:
    """Test duplicate prompt ID detection across files."""

    def test_no_duplicates(self, validator):
        all_seen: set[str] = set()
        dups, cross = validator._check_prompt_id_duplicates("file.md", ["id1", "id2"], all_seen)
        assert dups == set()
        assert cross == []

    def test_within_file_duplicates(self, validator):
        all_seen: set[str] = set()
        dups, cross = validator._check_prompt_id_duplicates("file.md", ["id1", "id1"], all_seen)
        assert "id1" in dups
        assert validator.has_errors()

    def test_cross_file_duplicates(self, validator):
        all_seen: set[str] = {"id1"}
        dups, cross = validator._check_prompt_id_duplicates("file2.md", ["id1"], all_seen)
        assert cross == ["id1"]
        assert validator.has_errors()


# ---------------------------------------------------------------------------
# _validate_prompt_format_logic
# ---------------------------------------------------------------------------


class TestValidatePromptFormatLogic:
    """Test prompt format validation logic."""

    def test_no_sections_no_ids(self, validator):
        result = validator._validate_prompt_format_logic("Just text.", "file.md")
        assert result is None

    def test_sections_but_no_ids(self, validator):
        content = "# Section\nSome text without prompt blocks."
        result = validator._validate_prompt_format_logic(content, "file.md")
        assert result is not None
        assert "no prompt ids" in result.lower()

    def test_valid_format(self, validator):
        content = "{prompt analyze}\nDo analysis\n{end_prompt}"
        result = validator._validate_prompt_format_logic(content, "file.md")
        assert result is None

    def test_unclosed_prompt_block(self, validator):
        content = "{prompt analyze}\nDo analysis without closing"
        result = validator._validate_prompt_format_logic(content, "file.md")
        assert result is not None
        assert "unclosed" in result.lower()

    def test_empty_prompt_content(self, validator):
        content = "{prompt analyze}\n{end_prompt}"
        result = validator._validate_prompt_format_logic(content, "file.md")
        assert result is not None
        assert "empty" in result.lower()

    def test_no_heading_start_with_sections(self, validator):
        content = "Some intro text\n# Section\n{prompt analyze}\nDo it\n{end_prompt}"
        result = validator._validate_prompt_format_logic(content, "file.md")
        assert result is not None
        assert "does not start with a markdown heading" in result.lower()


# ---------------------------------------------------------------------------
# _validate_single_prompt_file
# ---------------------------------------------------------------------------


class TestValidateSinglePromptFile:
    """Test single prompt file validation."""

    def test_valid_prompt_file(self, validator, tmp_path):
        f = tmp_path / "prompt.md"
        f.write_text("# My Prompt\n{prompt analyze}\nDo analysis\n{end_prompt}")
        all_ids: set[str] = set()
        count = validator._validate_single_prompt_file(f, all_ids)
        assert count == 1
        assert "analyze" in all_ids

    def test_oversized_file_returns_zero(self, validator, tmp_path):
        f = tmp_path / "big.md"
        f.write_text("x" * (101 * 1024))
        count = validator._validate_single_prompt_file(f, set())
        assert count == 0

    def test_file_with_no_sections_warns(self, validator, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("Just some text without headings or prompts.")
        count = validator._validate_single_prompt_file(f, set())
        assert count == 0
        assert len(validator.get_warnings()) > 0

    def test_file_with_duplicate_ids(self, validator, tmp_path):
        f = tmp_path / "dup.md"
        f.write_text("{prompt analyze}\nDo A\n{end_prompt}\n{prompt analyze}\nDo B\n{end_prompt}")
        count = validator._validate_single_prompt_file(f, set())
        assert count == 0
        assert validator.has_errors()


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


class TestValidateMethod:
    """Test the public validate() entry point."""

    def test_non_path_data(self, validator):
        result = validator.validate("not a path")
        assert result is False
        assert any("path object" in e.lower() for e in validator.get_errors())

    def test_nonexistent_directory(self, validator, tmp_path):
        result = validator.validate(tmp_path / "missing")
        assert result is False

    def test_path_is_file(self, validator, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        result = validator.validate(f)
        assert result is False
        assert any("not a directory" in e for e in validator.get_errors())

    def test_empty_directory_warns(self, validator, tmp_path):
        result = validator.validate(tmp_path)
        assert result is True
        assert len(validator.get_warnings()) > 0

    def test_directory_with_valid_prompts(self, validator, tmp_path):
        (tmp_path / "prompt1.md").write_text("# Prompt 1\n{prompt first}\nContent\n{end_prompt}")
        (tmp_path / "prompt2.md").write_text("# Prompt 2\n{prompt second}\nContent\n{end_prompt}")
        result = validator.validate(tmp_path)
        assert result is True
        assert not validator.has_errors()

    def test_cross_file_duplicates(self, validator, tmp_path):
        (tmp_path / "a.md").write_text("# Prompt A\n{prompt shared}\nContent A\n{end_prompt}")
        (tmp_path / "b.md").write_text("# Prompt B\n{prompt shared}\nContent B\n{end_prompt}")
        result = validator.validate(tmp_path)
        assert result is False
        assert any("duplicate" in e.lower() for e in validator.get_errors())
