"""A staged text is split into overlapping chunks by tokens, characters or a user
splitter, and ``dispatch_task`` calls a user function from the tools folder.
"""

import re
from pathlib import Path

import pytest

from agent_actions.errors import AgentActionsError, ConfigurationError
from agent_actions.input.preprocessing.transformation import string_transformer
from agent_actions.input.preprocessing.transformation.string_transformer import (
    StringProcessor,
    Tokenizer,
)


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    folder = tmp_path / "tools"
    folder.mkdir()
    return folder


class TestCallUserFunction:
    def test_the_context_text_is_passed_first_then_the_call_arguments(self, tools):
        (tools / "udf_shout_a.py").write_text(
            "def shout(text, suffix):\n    return text.upper() + suffix\n"
        )

        result = StringProcessor.call_user_function("udf_shout_a.shout, '?'", str(tools), "hi")

        assert result == "HI?"

    def test_without_context_text_only_the_call_arguments_are_passed(self, tools):
        (tools / "udf_join_b.py").write_text("def join_b(a, b):\n    return a + '-' + b\n")

        assert StringProcessor.call_user_function("udf_join_b.join_b, x, y", str(tools)) == "x-y"

    def test_a_bare_name_is_both_the_module_and_the_function(self, tools):
        (tools / "udf_bare_c.py").write_text("def udf_bare_c(text):\n    return len(text)\n")

        assert StringProcessor.call_user_function("udf_bare_c", str(tools), "four") == 4

    def test_without_a_tools_path_the_call_is_refused_with_the_config_key_to_set(self):
        with pytest.raises(ConfigurationError, match="No tools_path configured") as raised:
            StringProcessor.call_user_function("udf_any.fn", None, "x")

        assert raised.value.context["function_name"] == "udf_any.fn"

    def test_a_function_missing_from_its_module_is_named(self, tools):
        (tools / "udf_has_d.py").write_text("def present(text):\n    return text\n")

        with pytest.raises(ConfigurationError, match="Could not find function 'absent'"):
            StringProcessor.call_user_function("udf_has_d.absent", str(tools), "x")

    def test_a_module_missing_from_the_tools_folder_is_reported_as_not_importable(self, tools):
        with pytest.raises(ConfigurationError, match="Could not import module"):
            StringProcessor.call_user_function("udf_nowhere_e.fn", str(tools), "x")

    def test_a_value_error_inside_the_function_is_wrapped_with_its_name(self, tools):
        (tools / "udf_bad_f.py").write_text("def bad(text):\n    raise ValueError('nope')\n")

        with pytest.raises(
            AgentActionsError, match="Error executing user function 'bad'"
        ) as raised:
            StringProcessor.call_user_function("udf_bad_f.bad", str(tools), "x")

        assert not isinstance(raised.value, ConfigurationError)
        assert isinstance(raised.value.__cause__, ValueError)


class TestSplitByCharacters:
    def test_chunks_overlap_by_the_given_number_of_characters(self):
        chunks = Tokenizer.split_text_content("abcdefghijk", 4, 1, split_method="chars")

        assert chunks[:3] == ["abcd", "defg", "ghij"]

    def test_without_overlap_the_chunks_rebuild_the_text(self):
        chunks = Tokenizer.split_text_content("abcdefghij", 4, 0, split_method="chars")

        assert chunks == ["abcd", "efgh", "ij"]

    def test_empty_text_has_no_chunks(self):
        assert Tokenizer.split_text_content("", 4, 1, split_method="chars") == []

    def test_no_chunk_holds_only_the_overlap_of_the_one_before(self):
        chunks = Tokenizer.split_text_content("abcdefghij", 4, 1, split_method="chars")

        assert chunks == ["abcd", "defg", "ghij"]


class _WordEncoding:
    """Stands in for a tiktoken encoding offline: one token per word with its leading space."""

    def encode(self, text):
        return re.findall(r"\s*\S+", text)

    def decode(self, tokens):
        return "".join(tokens)


@pytest.fixture
def word_tokens(monkeypatch):
    def get_encoding(name):
        if name != "cl100k_base":
            raise ValueError(f"Unknown encoding {name}")
        return _WordEncoding()

    monkeypatch.setattr(string_transformer.tiktoken, "get_encoding", get_encoding)


@pytest.mark.usefixtures("word_tokens")
class TestSplitByTokens:
    def test_token_chunks_cover_the_text_with_overlap(self):
        text = "one two three four five six seven"

        chunks = Tokenizer.split_text_content(text, 3, 1)

        assert chunks[:3] == ["one two three", " three four five", " five six seven"]
        assert all(Tokenizer.num_tokens_from_string(c, "cl100k_base") <= 3 for c in chunks)

    def test_tokens_are_counted_with_the_named_encoding(self):
        assert Tokenizer.num_tokens_from_string("hello world", "cl100k_base") == 2

    def test_an_unknown_encoding_name_is_a_configuration_error(self):
        with pytest.raises(ConfigurationError, match="Invalid tiktoken encoding name 'nope'"):
            Tokenizer.num_tokens_from_string("x", "nope")

    def test_an_unknown_tokenizer_model_is_a_configuration_error(self):
        with pytest.raises(ConfigurationError):
            Tokenizer.split_text_content("some text", 3, 1, tokenizer_model="nope")


class TestSettingsAreChecked:
    @pytest.mark.parametrize(
        ("size", "overlap", "method", "message"),
        [
            (0, 0, "chars", "chunk_size must be a positive integer"),
            (4, -1, "chars", "overlap cannot be negative"),
            (4, 4, "chars", "overlap must be smaller than chunk_size"),
            (4, 5, "tiktoken", "overlap must be smaller than chunk_size"),
        ],
    )
    def test_an_impossible_setting_is_refused_before_splitting(
        self, size, overlap, method, message
    ):
        with pytest.raises(ConfigurationError, match=message):
            Tokenizer.split_text_content("text", size, overlap, split_method=method)


class TestOtherSplitters:
    def test_spacy_without_the_package_says_how_to_install_it(self, monkeypatch):
        monkeypatch.setattr(string_transformer, "HAS_SPACY", False)

        with pytest.raises(ConfigurationError, match="spaCy is not installed"):
            Tokenizer.split_text_content("One. Two.", 3, 1, split_method="spacy")

    def test_a_custom_split_method_is_called_from_the_tools_path(self, tools, monkeypatch):
        (tools / "pipe_split_g.py").write_text(
            "def pipe_split_g(text, size, overlap, model):\n"
            "    return [f'{part}:{size}:{overlap}:{model}' for part in text.split('|')]\n"
        )
        monkeypatch.setenv("TOOLS_PATH", str(tools))

        chunks = Tokenizer.split_text_content("a|b", 3, 1, split_method="pipe_split_g")

        assert chunks == ["a:3:1:cl100k_base", "b:3:1:cl100k_base"]

    def test_a_custom_split_method_missing_from_the_tools_path_is_named(self, tools, monkeypatch):
        monkeypatch.setenv("TOOLS_PATH", str(tools))

        with pytest.raises(ConfigurationError, match="custom split_method function 'no_split_h'"):
            Tokenizer.split_text_content("a", 3, 1, split_method="no_split_h")

    def test_a_failing_custom_split_method_is_wrapped_with_its_name(self, tools, monkeypatch):
        (tools / "boom_split_i.py").write_text(
            "def boom_split_i(*args):\n    raise RuntimeError('boom')\n"
        )
        monkeypatch.setenv("TOOLS_PATH", str(tools))

        with pytest.raises(AgentActionsError, match="custom split_method 'boom_split_i'") as raised:
            Tokenizer.split_text_content("a", 3, 1, split_method="boom_split_i")

        assert isinstance(raised.value.__cause__, RuntimeError)
