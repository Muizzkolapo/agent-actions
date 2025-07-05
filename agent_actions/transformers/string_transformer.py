"""Module for String Processing Functions"""

import importlib
import re
import os
import sys
from typing import List
import tiktoken
from pathlib import Path
from agent_actions.cli.exceptions import AgentActionsError, ConfigurationError

class StringProcessor:
    """
    A class for processing strings, including placeholder replacement and function call processing.
    """

    @staticmethod
    def process_as_string(input_text):
        """
        Ensures the input text is treated as a plain string, even if it contains dictionary-like patterns.

        Parameters:
            input_text (str): The input text that may contain dictionary-like patterns.

        Returns:
            str: The processed string treated as plain text.
        """
        if not isinstance(input_text, str):
            # Or raise TypeError("Input must be a string")
            return input_text
            
        pattern = re.compile(r'({.*?})')
        escaped_text = pattern.sub(lambda x: x.group(0).replace("{", "{{").replace("}", "}}"), input_text)
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
            args = [arg.strip().strip("'\"") for arg in call_args.split(',')]
            function_name = args[0]
            function_args = args[1:]

            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, str(Path(tools_path).resolve()))
            module = importlib.import_module(function_name)
            function = getattr(module, function_name)
            
            # Pass context_data_str as the first argument if it exists
            if context_data_str:
                result = function(context_data_str, *function_args)
            else:
                result = function(*function_args)

            return result
        except ImportError as e:
            raise ConfigurationError(f"Could not import module for UDF '{function_name}': {e}. Ensure '{tools_path}' is correct and module exists.") from e
        except AttributeError as e:
            raise ConfigurationError(f"Could not find function '{function_name}' in its module: {e}") from e
        except Exception as e: # Catch other errors during UDF execution
            # Consider a more specific UDFExecutionError
            raise AgentActionsError(f"Error executing user function '{function_name}': {str(e)}") from e


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
        except ValueError as e: # tiktoken.get_encoding can raise ValueError for unknown encoding
            raise ConfigurationError(f"Invalid tiktoken encoding name '{encoding_name}': {e}") from e
        except Exception as e: # Other unexpected tokenization errors
            # Log the error, but re-raise as it's a critical failure for this method's purpose
            raise AgentActionsError(f"Tokenization error for string '{string[:100]}...': {str(e)}") from e

    @staticmethod
    def split_text_content(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str = "cl100k_base",  # For tiktoken encoding
        split_method: str = "tiktoken",
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
            raise ValueError("chunk_size must be a positive integer.")
        if overlap < 0:
            raise ValueError("overlap cannot be negative.")
        if overlap >= chunk_size and split_method in ("tiktoken", "chars"):
            raise ValueError("overlap must be smaller than chunk_size for token/character splits.")

        try:
            if split_method == "tiktoken":
                return Tokenizer._split_with_tiktoken(text, chunk_size, overlap, tokenizer_model)
            elif split_method == "chars":
                return Tokenizer._split_by_chars(text, chunk_size, overlap)
            elif split_method == "spacy":
                return Tokenizer._split_with_spacy(text, chunk_size, overlap, tokenizer_model)
            else:
                return Tokenizer._split_with_custom_method(text, chunk_size, overlap, tokenizer_model, split_method)
        except ValueError:
            raise
        except Exception as e:  # General catch-all for unexpected issues
            raise AgentActionsError(f"Text splitting error for text '{text[:100]}...': {str(e)}") from e

    @staticmethod
    def _split_with_tiktoken(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
        encoding = tiktoken.get_encoding(tokenizer_model)
        try:
            tokens = encoding.encode(text)
        except Exception as e:
            raise AgentActionsError(f"Error encoding text with tiktoken model '{tokenizer_model}': {e}") from e

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
    def _split_with_spacy(text: str, chunk_size: int, overlap: int, tokenizer_model: str) -> List[str]:
        try:
            nlp = "None"  # spacy.load("en_core_web_sm")
        except OSError:
            raise ConfigurationError(
                "spaCy model 'en_core_web_sm' is not installed. Please install it to use 'spacy' split_method."
            )

        encoding = tiktoken.get_encoding(tokenizer_model)
        doc = nlp(text)
        sentences = [sent.text for sent in doc.sents]

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_tokens = len(encoding.encode(sentence))
            if current_length + sentence_tokens > chunk_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                overlap_sentences = current_chunk[-max(1, int(len(current_chunk) * overlap / chunk_size)) :]
                current_chunk = overlap_sentences
                current_length = sum(len(encoding.encode(s)) for s in current_chunk)

            current_chunk.append(sentence)
            current_length += sentence_tokens

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    @staticmethod
    def _split_with_custom_method(
        text: str,
        chunk_size: int,
        overlap: int,
        tokenizer_model: str,
        split_method: str,
    ) -> List[str]:
        try:
            tools_path = os.environ.get("TOOLS_PATH", "tools")
            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, str(Path(tools_path).resolve()))

            module = importlib.import_module(split_method)
            function = getattr(module, split_method)
            return function(text, chunk_size, overlap, tokenizer_model)
        except ImportError as e:
            raise ConfigurationError(f"Could not import custom split_method module '{split_method}': {e}") from e
        except AttributeError as e:
            raise ConfigurationError(
                f"Could not find custom split_method function '{split_method}' in its module: {e}"
            ) from e
        except Exception as e:
            raise AgentActionsError(f"Error executing custom split_method '{split_method}': {str(e)}") from e
