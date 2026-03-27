"""String processing, tokenization, and text chunking utilities."""

import importlib
import os
import re

import tiktoken

from agent_actions.errors import AgentActionsError, ConfigurationError
from agent_actions.utils.module_loader import load_module_from_directory

# Optional dependencies
try:
    import spacy  # type: ignore[import-not-found,import-untyped]

    HAS_SPACY = True
except ImportError:
    HAS_SPACY = False

_BRACE_PATTERN = re.compile("({.*?})")


class StringProcessor:
    """String processing including placeholder escaping and user-defined function calls."""

    @staticmethod
    def process_as_string(input_text):
        """Escape brace patterns so the string is not treated as a format template."""
        if not isinstance(input_text, str):
            return input_text
        escaped_text = _BRACE_PATTERN.sub(
            lambda x: x.group(0).replace("{", "{{").replace("}", "}}"), input_text
        )
        return escaped_text

    @staticmethod
    def call_user_function(call_args, tools_path=None, context_data_str=None):
        """Dynamically load and execute a user-defined function from the tools folder."""
        try:
            args = [arg.strip().strip("'\"") for arg in call_args.split(",")]
            full_function_name = args[0]
            function_args = args[1:]

            if "." in full_function_name:
                module_name, function_name = full_function_name.rsplit(".", 1)
            else:
                module_name = full_function_name
                function_name = full_function_name

            if tools_path:
                module = load_module_from_directory(module_name, tools_path)
            else:
                module = importlib.import_module(module_name)
            function = getattr(module, function_name)

            if context_data_str:
                result = function(context_data_str, *function_args)
            else:
                result = function(*function_args)
            return result
        except ImportError as e:
            raise ConfigurationError(
                f"Could not import module for UDF '{function_name}'",
                context={
                    "function_name": function_name,
                    "tools_path": tools_path,
                    "operation": "call_user_function",
                },
                cause=e,
            ) from e
        except AttributeError as e:
            raise ConfigurationError(
                f"Could not find function '{function_name}' in its module",
                context={"function_name": function_name, "operation": "call_user_function"},
                cause=e,
            ) from e
        except ValueError as e:
            raise AgentActionsError(
                f"Error executing user function '{function_name}'",
                context={"function_name": function_name, "operation": "call_user_function"},
                cause=e,
            ) from e


class Tokenizer:
    """Text tokenization and chunking with multiple split strategies."""

    @staticmethod
    def num_tokens_from_string(string: str, encoding_name: str) -> int:
        """Return the number of tokens in a text string."""
        try:
            encoding = tiktoken.get_encoding(encoding_name)
            num_tokens = len(encoding.encode(string))
            return num_tokens
        except ValueError as e:
            raise ConfigurationError(
                f"Invalid tiktoken encoding name '{encoding_name}'",
                context={"encoding_name": encoding_name, "operation": "num_tokens_from_string"},
                cause=e,
            ) from e
        except KeyError as e:
            string_preview = string[:100] if len(string) > 100 else string
            raise AgentActionsError(
                "Tokenization error",
                context={
                    "string_preview": string_preview,
                    "encoding_name": encoding_name,
                    "operation": "num_tokens_from_string",
                },
                cause=e,
            ) from e

    @staticmethod
    def split_text_content(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str = "cl100k_base",
        split_method: str = "tiktoken",
    ) -> list[str]:
        """Split text into overlapping chunks using the specified method."""
        if chunk_size <= 0:
            raise ConfigurationError(
                "chunk_size must be a positive integer",
                context={"chunk_size": chunk_size, "operation": "split_text_content"},
            )
        if overlap < 0:
            raise ConfigurationError(
                "overlap cannot be negative",
                context={"overlap": overlap, "operation": "split_text_content"},
            )
        if overlap >= chunk_size and split_method in ("tiktoken", "chars"):
            raise ConfigurationError(
                "overlap must be smaller than chunk_size for token/character splits",
                context={
                    "overlap": overlap,
                    "chunk_size": chunk_size,
                    "split_method": split_method,
                    "operation": "split_text_content",
                },
            )
        try:
            if split_method == "tiktoken":
                return Tokenizer._split_with_tiktoken(text, chunk_size, overlap, tokenizer_model)
            if split_method == "chars":
                return Tokenizer._split_by_chars(text, chunk_size, overlap)
            if split_method == "spacy":
                return Tokenizer._split_with_spacy(text, chunk_size, overlap, tokenizer_model)
            return Tokenizer._split_with_custom_method(
                text, chunk_size, overlap, tokenizer_model, split_method
            )
        except KeyError as e:
            text_preview = text[:100] if len(text) > 100 else text
            raise AgentActionsError(
                "Text splitting error",
                context={
                    "text_preview": text_preview,
                    "chunk_size": chunk_size,
                    "overlap": overlap,
                    "split_method": split_method,
                    "operation": "split_text_content",
                },
                cause=e,
            ) from e

    @staticmethod
    def _split_with_tiktoken(
        text: str, chunk_size: int, overlap: int, tokenizer_model: str
    ) -> list[str]:
        encoding = tiktoken.get_encoding(tokenizer_model)
        try:
            tokens = encoding.encode(text)
        except ValueError as e:
            raise AgentActionsError(
                f"Error encoding text with tiktoken model '{tokenizer_model}'",
                context={"tokenizer_model": tokenizer_model, "operation": "_split_with_tiktoken"},
                cause=e,
            ) from e
        chunks = []
        start_idx = 0
        while start_idx < len(tokens):
            end_idx = min(start_idx + chunk_size, len(tokens))
            chunk = tokens[start_idx:end_idx]
            decoded_chunk = encoding.decode(chunk)
            chunks.append(decoded_chunk)
            start_idx += chunk_size - overlap
        return chunks

    @staticmethod
    def _split_by_chars(text: str, chunk_size: int, overlap: int) -> list[str]:
        chunks = []
        start_idx = 0
        while start_idx < len(text):
            end_idx = min(start_idx + chunk_size, len(text))
            chunks.append(text[start_idx:end_idx])
            start_idx += chunk_size - overlap
        return chunks

    @staticmethod
    def _split_with_spacy(
        text: str, chunk_size: int, overlap: int, tokenizer_model: str
    ) -> list[str]:
        """Split text using spaCy sentence tokenization."""
        if not HAS_SPACY:
            raise ConfigurationError(
                "spaCy is not installed. "
                "Install with: uv pip install agent-actions[nlp] "
                "or uv pip install spacy>=3.0.0",
                context={"operation": "_split_with_spacy", "split_method": "spacy"},
            )
        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError as e:
            raise ConfigurationError(
                "spaCy model 'en_core_web_sm' is not installed. "
                "Download with: python -m spacy download en_core_web_sm",
                context={"operation": "_split_with_spacy", "model": "en_core_web_sm"},
                cause=e,
            ) from e
        encoding = tiktoken.get_encoding(tokenizer_model)
        doc = nlp(text)
        sentences = [sent.text for sent in doc.sents]
        chunks = []
        current_chunk: list[str] = []
        current_length = 0
        for sentence in sentences:
            sentence_tokens = len(encoding.encode(sentence))
            if current_length + sentence_tokens > chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                overlap_sentences = current_chunk[
                    -max(1, int(len(current_chunk) * overlap / chunk_size)) :
                ]
                current_chunk = overlap_sentences
                current_length = sum(len(encoding.encode(s)) for s in current_chunk)
            current_chunk.append(sentence)
            current_length += sentence_tokens
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    @staticmethod
    def _split_with_custom_method(
        text: str, chunk_size: int, overlap: int, tokenizer_model: str, split_method: str
    ) -> list[str]:
        try:
            tools_path = os.environ.get("TOOLS_PATH", "tools")
            if tools_path:
                module = load_module_from_directory(split_method, tools_path)
            else:
                module = importlib.import_module(split_method)
            function = getattr(module, split_method)
            result: list[str] = function(text, chunk_size, overlap, tokenizer_model)
            return result
        except ImportError as e:
            raise ConfigurationError(
                f"Could not import custom split_method module '{split_method}'",
                context={
                    "split_method": split_method,
                    "tools_path": tools_path,
                    "operation": "_split_with_custom_method",
                },
                cause=e,
            ) from e
        except AttributeError as e:
            raise ConfigurationError(
                f"Could not find custom split_method function '{split_method}' in its module",
                context={"split_method": split_method, "operation": "_split_with_custom_method"},
                cause=e,
            ) from e
        except Exception as e:
            raise AgentActionsError(
                f"Error executing custom split_method '{split_method}'",
                context={"split_method": split_method, "operation": "_split_with_custom_method"},
                cause=e,
            ) from e
