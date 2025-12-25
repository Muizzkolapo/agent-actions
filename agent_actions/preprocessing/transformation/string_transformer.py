"""Module for String Processing Functions"""
import importlib
import os
import re
import sys
from pathlib import Path
from typing import List

import tiktoken

from agent_actions.errors import AgentActionsException, ConfigurationError

# Optional dependencies
try:
    import spacy
    HAS_SPACY = True
except ImportError:
    HAS_SPACY = False

class StringProcessor:
    """
    A class for processing strings, including placeholder replacement and function call processing.
    """

    @staticmethod
    def process_as_string(input_text):
        """
        Ensures the input text is treated as a plain string.

        Handles text even if it contains dictionary-like patterns.

        Parameters:
            input_text (str): The input text that may contain dictionary-like patterns.

        Returns:
            str: The processed string treated as plain text.
        """
        if not isinstance(input_text, str):
            return input_text
        pattern = re.compile('({.*?})')
        escaped_text = pattern.sub(
            lambda x: x.group(0).replace('{', '{{').replace('}', '}}'),
            input_text
        )
        return escaped_text

    @staticmethod
    def call_user_function(call_args, tools_path=None, context_data_str=None):
        """
        Dynamically loads and executes a user-defined function from the tools folder.
        Always passes `context_data_str` as input.

        Parameters:
            call_args (str): The arguments to the function call.
            tools_path (str): Path to the tools directory.
            context_data_str (str): Documentation string to pass to the function.

        Returns:
            Any: The result returned by the user function.
        """
        try:
            args = [arg.strip().strip('\'"') for arg in call_args.split(',')]
            full_function_name = args[0]
            function_args = args[1:]

            if '.' in full_function_name:
                module_name, function_name = full_function_name.rsplit('.', 1)
            else:
                module_name = full_function_name
                function_name = full_function_name

            if tools_path:
                tools_path_resolved = Path(tools_path).resolve()
                # Add tools_path and all subdirectories to sys.path for nested module discovery
                if str(tools_path_resolved) not in sys.path:
                    sys.path.insert(0, str(tools_path_resolved))
                for subdir in tools_path_resolved.rglob('*'):
                    if subdir.is_dir() and not subdir.name.startswith('_'):
                        subdir_str = str(subdir)
                        if subdir_str not in sys.path:
                            sys.path.insert(0, subdir_str)

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
                    'function_name': function_name,
                    'tools_path': tools_path,
                    'operation': 'call_user_function'
                },
                cause=e
            ) from e
        except AttributeError as e:
            raise ConfigurationError(
                f"Could not find function '{function_name}' in its module",
                context={
                    'function_name': function_name,
                    'operation': 'call_user_function'
                },
                cause=e
            ) from e
        except ValueError as e:
            raise AgentActionsException(
                f"Error executing user function '{function_name}'",
                context={
                    'function_name': function_name,
                    'operation': 'call_user_function'
                },
                cause=e
            ) from e

class Tokenizer:
    """
    A class for handling tokenization of text.
    """

    @staticmethod
    def num_tokens_from_string(string: str, encoding_name: str) -> int:
        """Returns the number of tokens in a text string."""
        try:
            encoding = tiktoken.get_encoding(encoding_name)
            num_tokens = len(encoding.encode(string))
            return num_tokens
        except ValueError as e:
            raise ConfigurationError(
                f"Invalid tiktoken encoding name '{encoding_name}'",
                context={
                    'encoding_name': encoding_name,
                    'operation': 'num_tokens_from_string'
                },
                cause=e
            ) from e
        except KeyError as e:
            string_preview = string[:100] if len(string) > 100 else string
            raise AgentActionsException(
                'Tokenization error',
                context={
                    'string_preview': string_preview,
                    'encoding_name': encoding_name,
                    'operation': 'num_tokens_from_string'
                },
                cause=e
            ) from e

    @staticmethod
    def split_text_content(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str = 'cl100k_base',
        split_method: str = 'tiktoken'
    ) -> List[str]:
        """
        Split text into chunks of a specified size with a specified overlap.

        Parameters:
            text (str): The text to split into chunks.
            chunk_size (int): The size of each chunk in tokens or characters.
            overlap (int): The number of tokens or characters to overlap between chunks.
            tokenizer_model (str): The model name to use for tokenization and transformers.
                                  For tiktoken: encoding name (e.g., "cl100k_base")
                                  For transformers: model name (e.g., "all-MiniLM-L6-v2")
            split_method (str): The method to use for splitting text. Options:
                                "tiktoken" (default): Split by tokens using tiktoken
                                "chars": Split by characters
                                "spacy": Split using spaCy's sentence tokenization
                                "transformers": Split using sentence-transformers
                                Or a custom function name from the tools directory

        Returns:
            List[str]: A list of text chunks.
        """
        if chunk_size <= 0:
            raise ConfigurationError(
                'chunk_size must be a positive integer',
                context={'chunk_size': chunk_size, 'operation': 'split_text_content'}
            )
        if overlap < 0:
            raise ConfigurationError(
                'overlap cannot be negative',
                context={'overlap': overlap, 'operation': 'split_text_content'}
            )
        if overlap >= chunk_size and split_method in ('tiktoken', 'chars'):
            raise ConfigurationError(
                'overlap must be smaller than chunk_size for token/character splits',
                context={
                    'overlap': overlap,
                    'chunk_size': chunk_size,
                    'split_method': split_method,
                    'operation': 'split_text_content'
                }
            )
        try:
            if split_method == 'tiktoken':
                return Tokenizer._split_with_tiktoken(
                    text, chunk_size, overlap, tokenizer_model
                )
            if split_method == 'chars':
                return Tokenizer._split_by_chars(text, chunk_size, overlap)
            if split_method == 'spacy':
                return Tokenizer._split_with_spacy(
                    text, chunk_size, overlap, tokenizer_model
                )
            return Tokenizer._split_with_custom_method(
                text, chunk_size, overlap, tokenizer_model, split_method
            )
        except KeyError as e:
            text_preview = text[:100] if len(text) > 100 else text
            raise AgentActionsException(
                'Text splitting error',
                context={
                    'text_preview': text_preview,
                    'chunk_size': chunk_size,
                    'overlap': overlap,
                    'split_method': split_method,
                    'operation': 'split_text_content'
                },
                cause=e
            ) from e

    @staticmethod
    def _split_with_tiktoken(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str
    ) -> List[str]:
        encoding = tiktoken.get_encoding(tokenizer_model)
        try:
            tokens = encoding.encode(text)
        except ValueError as e:
            raise AgentActionsException(
                f"Error encoding text with tiktoken model '{tokenizer_model}'",
                context={
                    'tokenizer_model': tokenizer_model,
                    'operation': '_split_with_tiktoken'
                },
                cause=e
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
    def _split_by_chars(text: str, chunk_size: int, overlap: int) -> List[str]:
        chunks = []
        start_idx = 0
        while start_idx < len(text):
            end_idx = min(start_idx + chunk_size, len(text))
            chunks.append(text[start_idx:end_idx])
            start_idx += chunk_size - overlap
        return chunks

    @staticmethod
    def _split_with_spacy(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str
    ) -> List[str]:
        """
        Split text using spaCy's sentence tokenization.

        Requires spaCy to be installed: pip install agent-actions[nlp]
        And the language model: python -m spacy download en_core_web_sm
        """
        if not HAS_SPACY:
            raise ConfigurationError(
                'spaCy is not installed. '
                'Install with: pip install agent-actions[nlp] '
                'or pip install spacy>=3.0.0',
                context={'operation': '_split_with_spacy', 'split_method': 'spacy'}
            )
        try:
            nlp = spacy.load('en_core_web_sm')
        except OSError as e:
            raise ConfigurationError(
                "spaCy model 'en_core_web_sm' is not installed. "
                "Download with: python -m spacy download en_core_web_sm",
                context={'operation': '_split_with_spacy', 'model': 'en_core_web_sm'},
                cause=e
            ) from e
        encoding = tiktoken.get_encoding(tokenizer_model)
        doc = nlp(text)
        sentences = [sent.text for sent in doc.sents]
        chunks = []
        current_chunk = []
        current_length = 0
        for sentence in sentences:
            sentence_tokens = len(encoding.encode(sentence))
            if current_length + sentence_tokens > chunk_size and current_chunk:
                chunks.append(' '.join(current_chunk))
                overlap_sentences = current_chunk[
                    -max(1, int(len(current_chunk) * overlap / chunk_size)):
                ]
                current_chunk = overlap_sentences
                current_length = sum((len(encoding.encode(s)) for s in current_chunk))
            current_chunk.append(sentence)
            current_length += sentence_tokens
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        return chunks

    @staticmethod
    def _split_with_custom_method(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str,
        split_method: str
    ) -> List[str]:
        try:
            tools_path = os.environ.get('TOOLS_PATH', 'tools')
            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, str(Path(tools_path).resolve()))
            module = importlib.import_module(split_method)
            function = getattr(module, split_method)
            return function(text, chunk_size, overlap, tokenizer_model)
        except ImportError as e:
            raise ConfigurationError(
                f"Could not import custom split_method module '{split_method}'",
                context={
                    'split_method': split_method,
                    'tools_path': tools_path,
                    'operation': '_split_with_custom_method'
                },
                cause=e
            ) from e
        except AttributeError as e:
            raise ConfigurationError(
                f"Could not find custom split_method function '{split_method}' "
                "in its module",
                context={
                    'split_method': split_method,
                    'operation': '_split_with_custom_method'
                },
                cause=e
            ) from e
        except Exception as e:
            raise AgentActionsException(
                f"Error executing custom split_method '{split_method}'",
                context={
                    'split_method': split_method,
                    'operation': '_split_with_custom_method'
                },
                cause=e
            ) from e
