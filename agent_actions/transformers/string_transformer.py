"""Module for String Processing Functions"""

import importlib
import os
import re
import sys
import textwrap
from typing import List
import tiktoken
from sentence_transformers import SentenceTransformer

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
            print(f"Invalid input type: {type(input_text).__name__}")
            return input_text
            
        pattern = re.compile(r'({.*?})')
        escaped_text = pattern.sub(lambda x: x.group(0).replace("{", "{{").replace("}", "}}"), input_text)
        return escaped_text

    @staticmethod
    def replace_placeholders(prompt, content_dict):
        """
        Replace placeholders in the prompt string with values from content_dict.

        Parameters:
            prompt (str): The prompt string containing placeholders.
            content_dict (dict): A dictionary containing the values to replace placeholders.

        Returns:
            str: The prompt with placeholders replaced by actual values.
        """
        def convert_to_string(value):
            if isinstance(value, list):
                return ", ".join([str(v) if isinstance(v, dict) else str(v) for v in value])
            return str(value)

        if not isinstance(content_dict, dict) or not content_dict:
            return prompt

        placeholders = re.findall(r'return_collection\[(.*?)\]', prompt)
        for placeholder in placeholders:
            placeholder_keys = [key.strip() for key in placeholder.split(',')]
            replacements = [f"{key}: {convert_to_string(content_dict[key])}" for key in placeholder_keys if key in content_dict]
            replacement_text = ', '.join(replacements)
            prompt = prompt.replace(f'return_collection[{placeholder}]', replacement_text)

        return prompt

    @staticmethod
    def replace_guid_placeholder(data, guid):
        """
        Replace the placeholder 'return_collection{{source_context}}' with the specified GUID in a string.

        Parameters:
            data (str): The string to process.
            guid (str): The GUID to replace the placeholder with.

        Returns:
            str: The updated string with the placeholder replaced.
        """
        if not isinstance(data, str):
            return data

        replaced_data = data.replace('return_collection{{source_context}}', guid)
        cleaned_content = textwrap.dedent(replaced_data).strip()
        return cleaned_content

    @staticmethod
    def process_text_with_function_calls(text, tools_path=None, context_data_str=None):
        """
        Replace multiple dispatch_task() calls in text with the result of their corresponding function.
        Always passes `context_data_str` to the function.

        Parameters:
            text (str or list): The text containing dispatch_task() calls.
            tools_path (str): The path to the tools directory.
            context_data_str (str): Documentation string to pass to the functions.

        Returns:
            str or list: The text with dispatch_task() calls replaced by function outputs.
        """
        def process_single_text(single_text):
            if not isinstance(single_text, str):
                single_text = str(single_text)
            function_call_pattern = r"dispatch_task\('(\w+)'\)"
            function_calls = re.findall(function_call_pattern, single_text)

            if not function_calls:
                return single_text

            for function_name in function_calls:
                try:
                    transformed_text = StringProcessor.call_user_function(function_name, tools_path, context_data_str)
                    if transformed_text is None:
                        transformed_text = "Error: No valid return from function."
                    single_text = single_text.replace(f"dispatch_task('{function_name}')", transformed_text, 1)
                except Exception as e:
                    print(f"Function call error for '{function_name}': {str(e)}")

            return single_text

        if isinstance(text, list):
            return [process_single_text(str(item)) for item in text]
        elif isinstance(text, str):
            return process_single_text(text)
        else:
            print(f"Invalid input type: {type(text).__name__}")
            return text

    @staticmethod
    def call_user_function(function_name, tools_path=None, context_data_str=None):
        """
        Dynamically loads and executes a user-defined function from the tools folder.
        Always passes `context_data_str` as input.

        Parameters:
            function_name (str): Name of the function to call.
            tools_path (str): Path to the tools directory.
            context_data_str (str): Documentation string to pass to the function.

        Returns:
            Any: The result returned by the user function.
        """
        try:
            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, os.path.abspath(tools_path))
            module = importlib.import_module(function_name)
            function = getattr(module, function_name)
            result = function(context_data_str) if context_data_str else function()
            return result
        except Exception as e:
            print(f"User function error for '{function_name}': {str(e)}")


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
        except Exception as e:
            print(f"Tokenization error for string '{string[:100]}...': {str(e)}")
            return 0

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
            print("Error: chunk_size must be a positive integer.")
            return []
        if overlap < 0:
            print("Error: overlap cannot be negative.")
            return []
        if overlap >= chunk_size and split_method in ("tiktoken", "chars"):
            print("Error: overlap must be smaller than chunk_size for token/character splits.")
            return []

        try:
            # ---------------------------------------------------------------------
            # 1. Tiktoken-based splitting
            # ---------------------------------------------------------------------
            if split_method == "tiktoken":
                encoding = tiktoken.get_encoding(tokenizer_model)
                tokens = encoding.encode(text)

                chunks = []
                start_idx = 0
                while start_idx < len(tokens):
                    end_idx = min(start_idx + chunk_size, len(tokens))
                    chunk = tokens[start_idx:end_idx]
                    decoded_chunk = encoding.decode(chunk)
                    chunks.append(decoded_chunk)
                    start_idx += (chunk_size - overlap)

                return chunks

            # ---------------------------------------------------------------------
            # 2. Character-based splitting
            # ---------------------------------------------------------------------
            elif split_method == "chars":
                chunks = []
                start_idx = 0
                while start_idx < len(text):
                    end_idx = min(start_idx + chunk_size, len(text))
                    chunks.append(text[start_idx:end_idx])
                    start_idx += (chunk_size - overlap)

                return chunks

            # ---------------------------------------------------------------------
            # 3. spaCy-based splitting
            # ---------------------------------------------------------------------
            elif split_method == "spacy":
                try:
                    nlp = "None" #spacy.load("en_core_web_sm")
                except OSError:
                    print("spaCy model 'en_core_web_sm' is not installed.")
                    return []

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
                        overlap_sentences = current_chunk[-max(1, int(len(current_chunk) * overlap / chunk_size)):]
                        current_chunk = overlap_sentences
                        current_length = sum(len(encoding.encode(s)) for s in current_chunk)

                    current_chunk.append(sentence)
                    current_length += sentence_tokens

                if current_chunk:
                    chunks.append(" ".join(current_chunk))

                return chunks

            # ---------------------------------------------------------------------
            # 5. Custom user-defined method
            # ---------------------------------------------------------------------
            else:
                try:
                    tools_path = os.environ.get("TOOLS_PATH", "tools")
                    if tools_path and tools_path not in sys.path:
                        sys.path.insert(0, os.path.abspath(tools_path))

                    module = importlib.import_module(split_method)
                    function = getattr(module, split_method)
                    return function(text, chunk_size, overlap, tokenizer_model)
                except Exception as e:
                    print(f"User function error for '{split_method}': {str(e)}")
                    return []

        except Exception as e:
            print(f"Tokenization error for text '{text[:100]}...': {str(e)}")
            return []