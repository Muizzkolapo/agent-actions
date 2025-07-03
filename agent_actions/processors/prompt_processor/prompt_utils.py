"""Module for String Processing Functions"""

import re
import textwrap
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.cli.exceptions import AgentActionsError, ConfigurationError


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
        ci_content = {str(k).lower(): (k, v) for k, v in content_dict.items()}

        pattern = re.compile(r'return_collection\[(.*?)\]', flags=re.IGNORECASE)

        def repl(match):
            placeholder = match.group(1)
            placeholder_keys = [key.strip() for key in placeholder.split(',')]
            replacements = []
            for key in placeholder_keys:
                original = ci_content.get(key.lower())
                if original:
                    orig_key, value = original
                    replacement = f"{orig_key}: {convert_to_string(value)}"
                    replacements.append(replacement)
                    used_keys.add(orig_key)
            return ', '.join(replacements)

        prompt = pattern.sub(repl, prompt)

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

        replaced_data = re.sub(
            r'return_collection\{\{source_context\}\}',
            guid,
            data,
            flags=re.IGNORECASE,
        )
        cleaned_content = textwrap.dedent(replaced_data).strip()
        return cleaned_content

    @staticmethod
    def inject_function_outputs_into_prompt(prompt_config,
                                            tools_path=None,
                                            context_data_str=None,
                                            agent_config=None):
        """
        Replace multiple dispatch_task() calls in prompt_config with the result of their
        corresponding function.
        Always passes `context_data_str` to the function.

        Parameters:
            prompt_config (str or list): The prompt_config containing dispatch_task() calls.
            tools_path (str): The path to the tools directory.
            context_data_str (str): Documentation string to pass to the functions.
            agent_config (dict): Agent configuration to check for 'add_dispatch' flag.

        Returns:
            tuple: (The prompt_config with dispatch_task() calls replaced by function outputs,
                    captured_results)
        """
        captured_results = {}

        def process_single_text(single_text):
            nonlocal captured_results
            if not isinstance(single_text, str):
                single_text = str(single_text)
            function_call_pattern = r"dispatch_task\('(\w+)'\)"
            function_calls = re.findall(function_call_pattern, single_text)

            if not function_calls:
                return single_text

            for function_name in function_calls:
                try:
                    transformed_text = StringProcessor.call_user_function(function_name,
                                                                        tools_path,
                                                                        context_data_str)
                    if agent_config and agent_config.get('add_dispatch'):
                        captured_results[function_name] = transformed_text
                    if transformed_text is None:
                        transformed_text = "Error: No valid return from function."
                    single_text = single_text.replace(f"dispatch_task('{function_name}')",
                                                    transformed_text,
                                                    1)
                except (AgentActionsError, ConfigurationError) as e:
                    # Re-raise the specific error to be caught by the main error handler
                    raise e
                except Exception as e:
                    # Wrap other exceptions in a standard error type
                    raise AgentActionsError(
                        f"An unexpected error occurred in function '{function_name}': {str(e)}"
                    ) from e

            return single_text

        if isinstance(prompt_config, list):
            processed_prompt = [process_single_text(str(item)) for item in prompt_config]
        elif isinstance(prompt_config, str):
            processed_prompt = process_single_text(prompt_config)
        else:
            processed_prompt = prompt_config

        return processed_prompt, captured_results
