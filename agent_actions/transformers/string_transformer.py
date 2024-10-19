"""Module for String Processing Functions"""

import importlib
import os
import re
import sys
import textwrap
import traceback
from typing import List
import tiktoken

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

        Raises:
            ValueError: If the input is not a string.
        """
        if not isinstance(input_text, str):
            raise ValueError("Input must be a string")
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

        # Check if content_dict is a dictionary and has keys
        if not isinstance(content_dict, dict) or not content_dict:
            return prompt

        # Find placeholders in the format return_collection[key1,key2]
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
    def process_text_with_function_calls(text, tools_path=None, input_documentation_str=None):
        """
        Replace multiple dispatch_task() calls in text with the result of their corresponding function.
        Always passes `input_documentation_str` to the function.

        Parameters:
            text (str or list): The text containing dispatch_task() calls.
            tools_path (str): The path to the tools directory.
            input_documentation_str (str): Documentation string to pass to the functions.

        Returns:
            str or list: The text with dispatch_task() calls replaced by function outputs.
        """
        def process_single_text(single_text):
            if not isinstance(single_text, str):
                single_text = str(single_text)  # Ensure the input is a string
            function_call_pattern = r"dispatch_task\('(\w+)'\)"
            function_calls = re.findall(function_call_pattern, single_text)

            if not function_calls:
                return single_text

            for function_name in function_calls:
                try:
                    transformed_text = StringProcessor.call_user_function(function_name, tools_path, input_documentation_str)
                    if transformed_text is None:
                        transformed_text = "Error: No valid return from function."
                    single_text = single_text.replace(f"dispatch_task('{function_name}')", transformed_text, 1)
                except Exception as e:
                    print(f"Error calling function {function_name}: {e}")

            return single_text

        if isinstance(text, list):
            return [process_single_text(str(item)) for item in text]  # Ensure all list items are strings
        elif isinstance(text, str):
            return process_single_text(text)
        else:
            raise TypeError(f"Expected text to be a string or list, got {type(text)}")


    @staticmethod
    def call_user_function(function_name, tools_path=None, input_documentation_str=None):
        """
        Dynamically loads and executes a user-defined function from the tools folder.
        Always passes `input_documentation_str` as input.

        Parameters:
            function_name (str): Name of the function to call.
            tools_path (str): Path to the tools directory.
            input_documentation_str (str): Documentation string to pass to the function.

        Returns:
            Any: The result returned by the user function.

        Raises:
            Exception: If the function cannot be called or an error occurs.
        """
        try:
            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, os.path.abspath(tools_path))
            module = importlib.import_module(function_name)
            function = getattr(module, function_name)
            result = function(input_documentation_str) if input_documentation_str else function()
            return result
        except Exception as exception:
            print(f"Error in call_user_function for {function_name}:")
            print(f"Exception type: {type(exception).__name__}")
            print(f"Exception message: {str(exception)}")
            print("Traceback:")
            traceback.print_exc()
            raise



# Tokenization Functions

class Tokenizer:
    """
    A class for handling tokenization of text.
    """

    @staticmethod
    def num_tokens_from_string(string: str, encoding_name: str) -> int:
        """Returns the number of tokens in a text string."""
        encoding = tiktoken.get_encoding(encoding_name)
        num_tokens = len(encoding.encode(string))
        return num_tokens

    @staticmethod
    def split_text_content(text: str, chunk_size: int, overlap: int, encoding_name: str = "cl100k_base") -> List[str]:
        """Split text into chunks of a specified size with a specified overlap."""
        encoding = tiktoken.get_encoding(encoding_name)
        tokens = encoding.encode(text)
        chunks = []
        start_idx = 0
        while start_idx < len(tokens):
            end_idx = min(start_idx + chunk_size, len(tokens))
            chunk = tokens[start_idx:end_idx]
            decoded_chunk = encoding.decode(chunk)
            chunks.append(decoded_chunk)
            start_idx += chunk_size - overlap
        return chunks
