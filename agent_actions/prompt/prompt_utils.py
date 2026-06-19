"""Module for String Processing Functions"""

import re
from typing import Any

from agent_actions.errors import AgentActionsError
from agent_actions.input.preprocessing.transformation.string_transformer import StringProcessor


class PromptUtils:
    """
    A class for processing strings, including field reference replacement
    and function call processing.
    """

    @staticmethod
    def process_dispatch_in_text(
        text: str,
        tools_path: str,
        context_data_str: str,
        agent_config: dict | None = None,
        captured_results: dict | None = None,
        preserve_type_on_exact_match: bool = False,
    ):
        """
        Process dispatch_task() calls in a single string.

        Args:
            text: The text to process
            tools_path: Path to tools directory
            context_data_str: Context data string to pass to functions
            agent_config: Agent configuration
            captured_results: Dictionary to aggregate results into (modified in-place)
            preserve_type_on_exact_match: If True and the text is exactly one
                dispatch call, return the raw result.

        Returns:
            Processed text (str) or raw result (Any) if preserve_type_on_exact_match is True
        """
        if captured_results is None:
            captured_results = {}

        pattern = r'dispatch_task\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'

        # Optimization: Check for exact match first if type preservation is requested
        if preserve_type_on_exact_match:
            # We strip whitespace to be lenient, but strictly it should match the pattern
            stripped = text.strip()
            match = re.fullmatch(pattern, stripped)
            if match:
                function_name = match.group(1)
                try:
                    transformed_text = StringProcessor.call_user_function(
                        function_name, tools_path, context_data_str
                    )
                    if agent_config and agent_config.get("add_dispatch"):
                        captured_results[function_name] = transformed_text
                    if transformed_text is None:
                        # Type-preserving mode: return None so the caller/schema
                        # can treat the field as absent. In string-replacement mode
                        # (below, line 90) we substitute an error string because the
                        # result must remain a str.
                        return None
                    return transformed_text
                except AgentActionsError:
                    # Let known exceptions pass through without wrapping
                    raise
                except Exception as e:
                    raise AgentActionsError(
                        f"An unexpected error occurred in function '{function_name}': {str(e)}"
                    ) from e

        matches = re.finditer(pattern, text)
        replacements = []
        for match in matches:
            full_match = match.group(0)
            function_name = match.group(1)
            replacements.append((match.start(), match.end(), function_name, full_match))

        for start, end, function_name, _full_match in reversed(replacements):
            try:
                transformed_text = StringProcessor.call_user_function(
                    function_name, tools_path, context_data_str
                )
                if agent_config and agent_config.get("add_dispatch"):
                    captured_results[function_name] = transformed_text
                if transformed_text is None:
                    raise AgentActionsError(
                        f"dispatch_task('{function_name}') returned None. "
                        f"The function must return a value."
                    )
                text = text[:start] + str(transformed_text) + text[end:]
            except AgentActionsError:
                # Let known exceptions pass through without wrapping
                raise
            except Exception as e:
                raise AgentActionsError(
                    f"An unexpected error occurred in function '{function_name}': {str(e)}"
                ) from e
        return text

    @staticmethod
    def inject_function_outputs_into_prompt(
        prompt_config, tools_path=None, context_data_str=None, agent_config=None
    ):
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
        captured_results: dict[str, Any] = {}

        if isinstance(prompt_config, list):
            processed_prompt = [
                PromptUtils.process_dispatch_in_text(
                    str(item), tools_path, context_data_str, agent_config, captured_results
                )
                for item in prompt_config
            ]
        elif isinstance(prompt_config, str):
            processed_prompt = PromptUtils.process_dispatch_in_text(
                prompt_config, tools_path, context_data_str, agent_config, captured_results
            )
        else:
            processed_prompt = prompt_config
        return (processed_prompt, captured_results)
