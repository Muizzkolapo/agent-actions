"""Module for String Processing Functions"""

import re
import json
from agent_actions.agents.transformers.string_transformer import StringProcessor
from agent_actions.core.exceptions import AgentActionsException, ConfigurationError


class PromptUtils:
    """
    A class for processing strings, including field reference replacement and function call processing.
    """

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
            """
            Process dispatch_task('function_name') calls.

            Simple design:
            - dispatch_task() takes only a function name (no other arguments)
            - The function receives the same context_data as the LLM
            - No complex parsing needed - just extract function name from quotes
            """
            nonlocal captured_results
            if not isinstance(single_text, str):
                single_text = str(single_text)

            # Simple pattern: dispatch_task('function_name') or dispatch_task("function_name")
            # Match: dispatch_task(' or dispatch_task("
            # Then capture everything until the closing quote
            # Then match )
            pattern = r"dispatch_task\(['\"]([^'\"]+)['\"]\)"

            matches = re.finditer(pattern, single_text)

            # Process in reverse to avoid position shifts during replacement
            replacements = []
            for match in matches:
                full_match = match.group(0)  # dispatch_task('function_name')
                function_name = match.group(1)  # function_name
                replacements.append((match.start(), match.end(), function_name, full_match))

            # Process replacements in reverse order
            for start, end, function_name, full_match in reversed(replacements):
                try:
                    # Call the function with context_data (same data the LLM receives)
                    transformed_text = StringProcessor.call_user_function(
                        function_name,
                        tools_path,
                        context_data_str
                    )

                    if agent_config and agent_config.get('add_dispatch'):
                        captured_results[function_name] = transformed_text

                    if transformed_text is None:
                        transformed_text = "Error: No valid return from function."

                    # Replace the dispatch_task call with the function output
                    single_text = single_text[:start] + transformed_text + single_text[end:]
                except (AgentActionsException, ConfigurationError) as e:
                    # Re-raise the specific error to be caught by the main error handler
                    raise e
                except Exception as e:
                    # Wrap other exceptions in a standard error type
                    raise AgentActionsException(
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
        # Pattern: {word.word} or {word.word.word} etc.
        # Must have at least one dot, starts with letter/underscore
        pattern = r'\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)\}'
        references = []

        for match in re.finditer(pattern, prompt):
            full_ref = match.group(1)  # e.g., 'extractor.metrics.count'
            parts = full_ref.split('.')

            references.append({
                'reference': parts[0],      # 'extractor'
                'field_path': parts[1:],    # ['metrics', 'count']
                'full_match': match.group(0) # '{extractor.metrics.count}'
            })

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
        # Check reference exists
        if reference not in context:
            available = ', '.join(context.keys())
            raise ValueError(
                f"Reference '{reference}' not found. Available: [{available}]"
            )

        data = context[reference]

        # Navigate field path
        for field in field_path:
            if isinstance(data, dict) and field in data:
                data = data[field]
            elif isinstance(data, list) and field.isdigit():
                # Handle array index: {agent.items.0}
                idx = int(field)
                if 0 <= idx < len(data):
                    data = data[idx]
                else:
                    raise ValueError(
                        f"Index {idx} out of range for array in '{reference}'"
                    )
            else:
                field_str = '.'.join(field_path)
                raise ValueError(
                    f"Field '{field_str}' not found in '{reference}'"
                )

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

        for ref in references:
            try:
                value = PromptUtils.resolve_field_reference(
                    ref['reference'],
                    ref['field_path'],
                    context
                )

                # Convert to string
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value, indent=2)
                else:
                    value_str = str(value)

                # Replace in prompt
                prompt = prompt.replace(ref['full_match'], value_str)

            except ValueError as e:
                # Re-raise with context
                raise ValueError(
                    f"Error resolving {ref['full_match']}: {str(e)}"
                )

        return prompt
