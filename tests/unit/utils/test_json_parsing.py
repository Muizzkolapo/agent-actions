"""Tests for agent_actions.utils.json_parsing — shared LLM JSON parsing."""

import pytest

from agent_actions.utils.json_parsing import parse_llm_json, strip_code_fences


class TestStripCodeFences:
    """strip_code_fences removes markdown code fences when present."""

    def test_json_fence(self):
        text = '```json\n{"a": 1}\n```'
        assert strip_code_fences(text) == '{"a": 1}'

    def test_plain_fence(self):
        text = '```\n{"a": 1}\n```'
        assert strip_code_fences(text) == '{"a": 1}'

    def test_no_fence(self):
        text = '{"a": 1}'
        assert strip_code_fences(text) == '{"a": 1}'

    def test_surrounding_whitespace(self):
        text = '  \n```json\n{"a": 1}\n```\n  '
        assert strip_code_fences(text) == '{"a": 1}'

    def test_multiline_content(self):
        text = '```json\n{\n  "a": 1,\n  "b": 2\n}\n```'
        result = strip_code_fences(text)
        assert '"a": 1' in result
        assert '"b": 2' in result


class TestParseLlmJson:
    """parse_llm_json tries json.loads, fence strip, then json_repair."""

    def test_plain_json_dict(self):
        result = parse_llm_json('{"a": 1}')
        assert result == {"a": 1}

    def test_plain_json_list(self):
        result = parse_llm_json('[{"a": 1}]')
        assert result == [{"a": 1}]

    def test_code_fenced_json(self):
        result = parse_llm_json('```json\n{"question": "What?"}\n```')
        assert isinstance(result, dict)
        assert result["question"] == "What?"

    def test_trailing_comma_repair(self):
        result = parse_llm_json('{"a": 1, "b": 2,}')
        assert isinstance(result, dict)
        assert result["a"] == 1
        assert result["b"] == 2

    def test_garbage_returns_string(self):
        content = "not valid json {{{"
        result = parse_llm_json(content)
        assert isinstance(result, str)
        assert result == content

    def test_empty_string_returns_string(self):
        result = parse_llm_json("")
        assert isinstance(result, str)

    def test_whitespace_only_returns_string(self):
        result = parse_llm_json("   \n  ")
        assert isinstance(result, str)

    @pytest.mark.parametrize(
        "content,expected_key",
        [
            ('```json\n{"options": ["A", "B"]}\n```', "options"),
            ('```\n{"score": 5}\n```', "score"),
        ],
        ids=["json-tag", "no-tag"],
    )
    def test_various_fence_styles(self, content, expected_key):
        result = parse_llm_json(content)
        assert isinstance(result, dict)
        assert expected_key in result
