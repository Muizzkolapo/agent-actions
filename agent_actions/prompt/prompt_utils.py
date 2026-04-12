"""Module for String Processing Functions"""

import json
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

    @staticmethod
    def parse_field_references(prompt: str) -> list:
        """
        Parse {reference.field} patterns from prompt.

        Pattern matches:
        - {source.field}
        - {agent.field}
        - {agent.nested.field}
        - {agent.items.0} (array index)

        Args:
            prompt: Prompt string with field references

        Returns:
            List of dicts with 'reference', 'field_path', and 'full_match'
        """
        pattern = r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)\}"
        references = []
        for match in re.finditer(pattern, prompt):
            full_ref = match.group(1)
            parts = full_ref.split(".")
            references.append(
                {
                    "reference": parts[0],
                    "field_path": parts[1:],
                    "full_match": match.group(0),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
        return references

    @staticmethod
    def resolve_field_reference(reference: str, field_path: list, context: dict):
        """
        Resolve a field reference to its value in the context.

        Args:
            reference: Reference name (e.g., 'source', 'extractor')
            field_path: List of field names (e.g., ['metrics', 'count'])
            context: Dict with available references

        Returns:
            Resolved value

        Raises:
            ValueError: If reference or field not found
        """
        if reference not in context:
            available = ", ".join(context.keys())
            raise ValueError(f"Reference '{reference}' not found. Available: [{available}]")
        data = context[reference]
        for field in field_path:
            if isinstance(data, dict) and field in data:
                data = data[field]
            elif isinstance(data, list) and field.isdigit():
                idx = int(field)
                if 0 <= idx < len(data):
                    data = data[idx]
                else:
                    raise ValueError(f"Index {idx} out of range for array in '{reference}'")
            else:
                field_str = ".".join(field_path)
                raise ValueError(f"Field '{field_str}' not found in '{reference}'")
        return data

    @staticmethod
    def replace_field_references(prompt: str, context: dict) -> str:
        """
        Replace all {reference.field} patterns with their values.

        Args:
            prompt: Prompt string with field references
            context: Dict with available references

        Returns:
            Prompt with all references replaced

        Raises:
            ValueError: If reference or field not found
        """
        references = PromptUtils.parse_field_references(prompt)
        for ref in reversed(references):
            try:
                value = PromptUtils.resolve_field_reference(
                    ref["reference"], ref["field_path"], context
                )
                if isinstance(value, dict | list):
                    value_str = json.dumps(value, indent=2)
                else:
                    value_str = str(value)
                prompt = prompt[: ref["start"]] + value_str + prompt[ref["end"] :]
            except ValueError as e:
                raise ValueError(f"Error resolving {ref['full_match']}: {str(e)}") from e
        return prompt
