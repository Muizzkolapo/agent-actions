"""Tests for JSON repair strategies."""

import pytest
from agent_actions.reprompting.json_repair import JSONRepairStrategy, RepairResult


class TestJSONRepairStrategy:
    """Tests for JSONRepairStrategy class."""

    @pytest.fixture
    def repair(self):
        """Create a JSONRepairStrategy instance."""
        return JSONRepairStrategy()

    def test_valid_json_parses_directly(self, repair):
        """Test valid JSON is parsed directly."""
        result = repair.attempt_repair('{"name": "test"}')
        assert result.success is True
        assert result.data == {"name": "test"}
        assert result.repair_method == "direct_parse"

    def test_valid_json_array(self, repair):
        """Test valid JSON array is parsed."""
        result = repair.attempt_repair('[1, 2, 3]')
        assert result.success is True
        assert result.data == [1, 2, 3]

    def test_empty_input_fails(self, repair):
        """Test empty input fails with appropriate error."""
        result = repair.attempt_repair("")
        assert result.success is False
        assert "Empty" in result.error

    def test_whitespace_only_fails(self, repair):
        """Test whitespace-only input fails."""
        result = repair.attempt_repair("   \n\t  ")
        assert result.success is False


class TestStripMarkdown:
    """Tests for markdown stripping."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_strips_json_code_block(self, repair):
        """Test stripping ```json code block."""
        input_text = '```json\n{"name": "test"}\n```'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}
        assert result.repair_method == "strip_markdown"

    def test_strips_plain_code_block(self, repair):
        """Test stripping plain ``` code block."""
        input_text = '```\n{"name": "test"}\n```'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}

    def test_strips_code_block_with_extra_text(self, repair):
        """Test stripping code block with surrounding text."""
        input_text = 'Here is the JSON:\n```json\n{"name": "test"}\n```\nDone!'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}


class TestExtractJsonBlock:
    """Tests for JSON block extraction."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_extracts_json_object(self, repair):
        """Test extracting JSON object from text."""
        input_text = 'Here is the result: {"name": "test"} and more text'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}
        assert result.repair_method == "extract_json_block"

    def test_extracts_json_array(self, repair):
        """Test extracting JSON array from text."""
        input_text = 'The array is: [1, 2, 3] here.'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == [1, 2, 3]

    def test_extracts_nested_json(self, repair):
        """Test extracting nested JSON."""
        input_text = 'Result: {"outer": {"inner": "value"}} end'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"outer": {"inner": "value"}}


class TestFixTrailingCommas:
    """Tests for trailing comma fixing."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_fixes_trailing_comma_in_object(self, repair):
        """Test fixing trailing comma before }."""
        input_text = '{"name": "test",}'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}
        assert result.repair_method == "fix_trailing_commas"

    def test_fixes_trailing_comma_in_array(self, repair):
        """Test fixing trailing comma before ]."""
        input_text = '[1, 2, 3,]'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == [1, 2, 3]

    def test_fixes_trailing_comma_with_whitespace(self, repair):
        """Test fixing trailing comma with whitespace."""
        input_text = '{"name": "test" ,  }'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}


class TestFixQuotes:
    """Tests for quote fixing."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_fixes_single_quote_keys(self, repair):
        """Test fixing single quotes on keys."""
        input_text = "{'name': 'test'}"
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}
        assert result.repair_method == "fix_quotes"


class TestCloseBrackets:
    """Tests for closing unclosed brackets."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_closes_unclosed_object(self, repair):
        """Test closing unclosed object brace."""
        input_text = '{"name": "test"'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}
        assert result.repair_method == "close_brackets"

    def test_closes_unclosed_array(self, repair):
        """Test closing unclosed array bracket."""
        input_text = '[1, 2, 3'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == [1, 2, 3]

    def test_closes_nested_unclosed(self, repair):
        """Test closing nested unclosed brackets."""
        input_text = '{"items": [1, 2'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"items": [1, 2]}

    def test_removes_trailing_comma_before_close(self, repair):
        """Test removing trailing comma before closing."""
        input_text = '{"name": "test",'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}


class TestRepairAndParse:
    """Tests for convenience repair_and_parse method."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_repair_and_parse_success(self, repair):
        """Test repair_and_parse returns (data, method) on success."""
        data, method = repair.repair_and_parse('{"name": "test"}')
        assert data == {"name": "test"}
        assert method == "direct_parse"

    def test_repair_and_parse_failure(self, repair):
        """Test repair_and_parse returns (None, error) on failure."""
        data, error = repair.repair_and_parse("not json at all {{{}}")
        assert data is None
        assert error is not None


class TestComplexRepairScenarios:
    """Tests for complex real-world repair scenarios."""

    @pytest.fixture
    def repair(self):
        return JSONRepairStrategy()

    def test_llm_response_with_explanation(self, repair):
        """Test typical LLM response with explanation before JSON."""
        input_text = '''Here is the quiz question:

```json
{
  "question": "What is 2+2?",
  "answer": "4"
}
```

I hope this helps!'''
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data["question"] == "What is 2+2?"
        assert result.data["answer"] == "4"

    def test_truncated_json_object(self, repair):
        """Test repairing truncated JSON (common in streaming)."""
        input_text = '{"name": "test", "items": [1, 2, 3], "config": {"nested": "value"'
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data["name"] == "test"

    def test_multiple_issues(self, repair):
        """Test repairing JSON with multiple issues."""
        # Markdown + trailing comma
        input_text = '''```json
{"name": "test",}
```'''
        result = repair.attempt_repair(input_text)
        assert result.success is True
        assert result.data == {"name": "test"}
