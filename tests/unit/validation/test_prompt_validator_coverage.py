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
    """Test duplicate prompt ID detection within one file."""

    def test_no_duplicates(self, validator):
        assert validator._check_prompt_id_duplicates("file.md", ["id1", "id2"]) == set()
        assert validator.get_errors() == []

    def test_within_file_duplicates(self, validator):
        assert validator._check_prompt_id_duplicates("file.md", ["id1", "id1"]) == {"id1"}
        assert validator.get_errors() == ["Duplicate prompt IDs found in file 'file.md': id1."]


# ---------------------------------------------------------------------------
# _validate_prompt_format_logic
# ---------------------------------------------------------------------------


class TestValidatePromptFormatLogic:
    """Test prompt format validation logic."""

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("Just text.", id="no-sections-no-ids"),
            pytest.param("{prompt analyze}\nDo analysis\n{end_prompt}", id="valid"),
        ],
    )
    def test_accepted_format_returns_none(self, validator, content):
        assert validator._validate_prompt_format_logic(content, "file.md") is None

    @pytest.mark.parametrize(
        ("content", "fragment"),
        [
            pytest.param(
                "# Section\nSome text without prompt blocks.", "no prompt ids", id="sections-no-ids"
            ),
            pytest.param(
                "{prompt analyze}\nDo analysis without closing", "unclosed", id="unclosed"
            ),
            pytest.param("{prompt analyze}\n{end_prompt}", "empty", id="empty"),
            pytest.param(
                "Some intro text\n# Section\n{prompt analyze}\nDo it\n{end_prompt}",
                "does not start with a markdown heading",
                id="no-heading",
            ),
        ],
    )
    def test_bad_format_returns_message(self, validator, content, fragment):
        result = validator._validate_prompt_format_logic(content, "file.md")
        assert result is not None
        assert fragment in result.lower()


# ---------------------------------------------------------------------------
# _validate_single_prompt_file
# ---------------------------------------------------------------------------


class TestValidateSinglePromptFile:
    """Test single prompt file validation."""

    def test_valid_prompt_file(self, validator, tmp_path):
        f = tmp_path / "prompt.md"
        f.write_text("# My Prompt\n{prompt analyze}\nDo analysis\n{end_prompt}")
        count = validator._validate_single_prompt_file(f)
        assert count == 1
        assert validator.get_errors() == []

    def test_oversized_file_returns_zero(self, validator, tmp_path):
        f = tmp_path / "big.md"
        f.write_text("x" * (101 * 1024))
        count = validator._validate_single_prompt_file(f)
        assert count == 0

    def test_file_with_no_sections_warns(self, validator, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("Just some text without headings or prompts.")
        count = validator._validate_single_prompt_file(f)
        assert count == 0
        assert len(validator.get_warnings()) > 0

    def test_file_with_duplicate_ids(self, validator, tmp_path):
        f = tmp_path / "dup.md"
        f.write_text("{prompt analyze}\nDo A\n{end_prompt}\n{prompt analyze}\nDo B\n{end_prompt}")
        count = validator._validate_single_prompt_file(f)
        assert count == 0
        assert validator.has_errors()


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


class TestValidateMethod:
    """Test the public validate() entry point."""

    @pytest.mark.parametrize(
        "data",
        [pytest.param("not a list", id="string"), pytest.param(["a.md"], id="list-of-strings")],
    )
    def test_data_that_is_not_a_list_of_paths_is_an_error(self, validator, data):
        result = validator.validate(data)
        assert result is False
        assert validator.get_errors() == ["Validation data must be a list of prompt file paths."]

    def test_no_files_is_a_clean_pass_with_nothing_reported(self, validator):
        result = validator.validate([])
        assert result is True
        assert validator.get_errors() == []
        assert validator.get_warnings() == []

    def test_valid_files(self, validator, tmp_path):
        first = tmp_path / "prompt1.md"
        second = tmp_path / "prompt2.md"
        first.write_text("# Prompt 1\n{prompt first}\nContent\n{end_prompt}")
        second.write_text("# Prompt 2\n{prompt second}\nContent\n{end_prompt}")
        result = validator.validate([first, second])
        assert result is True
        assert validator.get_errors() == []
        assert validator.get_warnings() == []

    def test_only_the_given_files_are_checked(self, validator, tmp_path):
        given = tmp_path / "given.md"
        given.write_text("# Bad\n{prompt given}\n{end_prompt}")
        (tmp_path / "other.md").write_text("# Bad\n{prompt other}\n{end_prompt}")
        result = validator.validate([given])
        assert result is False
        assert validator.get_errors() == ["Empty prompt content for ID 'given' in file 'given.md'."]

    def test_an_id_in_two_files_is_not_reported(self, validator, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("# Prompt A\n{prompt shared}\nContent A\n{end_prompt}")
        b.write_text("# Prompt B\n{prompt shared}\n{end_prompt}")
        result = validator.validate([a, b])
        assert result is False
        assert validator.get_errors() == ["Empty prompt content for ID 'shared' in file 'b.md'."]
        assert validator.get_warnings() == []

    def test_a_file_given_under_two_names_is_checked_once(self, validator, tmp_path):
        real = tmp_path / "real.md"
        real.write_text("# Real\n{prompt real}\n{end_prompt}")
        alias = tmp_path / "alias.md"
        alias.symlink_to(real)
        other = tmp_path / "other.md"
        other.write_text("# Other\n{prompt other}\n{end_prompt}")
        result = validator.validate([alias, real, other])
        assert result is False
        assert validator.get_errors() == [
            "Empty prompt content for ID 'real' in file 'alias.md'.",
            "Empty prompt content for ID 'other' in file 'other.md'.",
        ]
