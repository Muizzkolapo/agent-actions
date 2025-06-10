"""Module for String Processing Functions"""

import re
import textwrap
from agent_actions.transformers.string_transformer import StringProcessor

class PromptUtils:
    """
    A class for processing strings, including placeholder replacement and function call processing.
    """
    @staticmethod
    def replace_placeholders(prompt, content_dict):
        """
        Replace placeholders in the prompt with values from content_dict,
        and remove used keys from the dict.

        Returns:
            tuple: (modified_prompt, cleaned_dict)
        """
        def convert_to_string(value):
            if isinstance(value, list):
                return ", ".join([str(v) if isinstance(v, dict) else str(v) for v in value])
            return str(value)

        if not isinstance(content_dict, dict) or not content_dict:
            return prompt, content_dict

        used_keys = set()
        placeholders = re.findall(r'return_collection\[(.*?)\]', prompt)
        for placeholder in placeholders:
            placeholder_keys = [key.strip() for key in placeholder.split(',')]
            replacements = []
            for key in placeholder_keys:
                if key in content_dict:
                    replacements.append(f"{key}: {convert_to_string(content_dict[key])}")
                    used_keys.add(key)
            replacement_text = ', '.join(replacements)
            prompt = prompt.replace(f'return_collection[{placeholder}]', replacement_text)

        cleaned_dict = {k: v for k, v in content_dict.items() if k not in used_keys}
        return prompt, cleaned_dict



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
    def inject_function_outputs_into_prompt(prompt_config, tools_path=None, context_data_str=None):
        """
        Replace multiple dispatch_task() calls in prompt_config with the result of their corresponding function.
        Always passes `context_data_str` to the function.

        Parameters:
            prompt_config (str or list): The prompt_config containing dispatch_task() calls.
            tools_path (str): The path to the tools directory.
            context_data_str (str): Documentation string to pass to the functions.

        Returns:
            str or list: The prompt_config with dispatch_task() calls replaced by function outputs.
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

        if isinstance(prompt_config, list):
            return [process_single_text(str(item)) for item in prompt_config]
        elif isinstance(prompt_config, str):
            return process_single_text(prompt_config)
        else:
            print(f"Invalid input type: {type(prompt_config).__name__}")