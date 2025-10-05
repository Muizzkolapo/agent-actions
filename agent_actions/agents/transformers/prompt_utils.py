"""Module for String Processing Functions"""

import re
import json
import textwrap
from agent_actions.agents.transformers.string_transformer import StringProcessor
from agent_actions.core.exceptions import AgentActionsException, ConfigurationError


class PromptUtils:
    """
    A class for processing strings, including placeholder replacement and function call processing.
    """
    @staticmethod
    def replace_placeholders(prompt, content_dict, warn_missing_keys=True):
        """
        Replace placeholders in the prompt with values from content_dict,
        and remove used keys from the dict.

        Args:
            prompt: The prompt string with placeholders
            content_dict: Dictionary containing replacement values
            warn_missing_keys: Whether to log warnings for missing return_collection keys
            
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
        
        # Handle nested structures - flatten the content_dict to find all keys
        def flatten_dict(d, parent_key=''):
            items = []
            if isinstance(d, dict):
                for k, v in d.items():
                    new_key = f"{parent_key}.{k}" if parent_key else k
                    if isinstance(v, dict):
                        items.extend(flatten_dict(v, new_key))
                    else:
                        items.append((new_key, v))
                        items.append((k, v))  # Also add the key without parent prefix
            elif isinstance(d, list):
                for i, item in enumerate(d):
                    if isinstance(item, dict):
                        items.extend(flatten_dict(item, f"{parent_key}[{i}]" if parent_key else f"[{i}]"))
            return items
        
        # Create a flattened version of content_dict
        flattened_items = flatten_dict(content_dict)
        ci_content = {str(k).lower(): (k, v) for k, v in flattened_items}

        pattern = re.compile(r'return_collection\[(.*?)\]', flags=re.IGNORECASE)

        def repl(match):
            placeholder = match.group(1)
            placeholder_keys = [key.strip() for key in placeholder.split(',')]
            replacements = []
            
            for key in placeholder_keys:
                original = ci_content.get(key.lower())
                if original:
                    orig_key, value = original
                    replacement = convert_to_string(value)
                    replacements.append(replacement)
                    used_keys.add(orig_key)
                else:
                    # Handle missing keys - log warning but provide cleaner fallback
                    if warn_missing_keys:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"return_collection key '{key}' not found in current context. Available keys: {list(content_dict.keys()) if content_dict else 'none'}")
                    # Provide cleaner fallback that doesn't clutter the prompt
                    replacement = "[missing]"
                    replacements.append(replacement)
            return ', '.join(replacements)

        prompt = pattern.sub(repl, prompt)

        cleaned_dict = {k: v for k, v in content_dict.items() if k not in used_keys}
        return prompt, cleaned_dict



    @staticmethod
    def replace_source_context_placeholder(data, source_content):
        """
        Replace the placeholder 'source_context{{...}}' with source content or selected fields.

        Parameters:
            data (str): The string to process.
            source_content (Any): The full source content (can be dict, list, or any JSON-serializable object).

        Returns:
            str: The updated string with the placeholder replaced.
        """
        if not isinstance(data, str):
            return data

        def replace_func(match):
            # Extract content between {{ }}
            field_spec = match.group(1).strip()
            
            # If empty, return full source content as JSON string
            if not field_spec:
                if isinstance(source_content, str):
                    return source_content
                return json.dumps(source_content, indent=2) if source_content else ""
            
            # Parse field selection (e.g., ['page_content'] or ['page_content', 'title'])
            try:
                # Safely evaluate the field list
                import ast
                fields = ast.literal_eval(field_spec)
                if not isinstance(fields, list):
                    # If not a list, treat as single field
                    fields = [field_spec.strip("'\"")]
                
                # Extract specified fields from source_content
                if isinstance(source_content, dict):
                    result = {}
                    for field in fields:
                        if field in source_content:
                            result[field] = source_content[field]
                    return json.dumps(result, indent=2) if result else ""
                else:
                    # If source_content is not a dict, return it as is
                    return json.dumps(source_content, indent=2) if source_content else ""
                    
            except (ValueError, SyntaxError):
                # If parsing fails, return empty string
                return ""

        # Replace source_context{{...}} pattern
        replaced_data = re.sub(
            r'source_context\{\{(.*?)\}\}',
            replace_func,
            data,
            flags=re.IGNORECASE | re.DOTALL,
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
            function_call_pattern = r"dispatch_task\((.*?)\)"
            function_calls = re.findall(function_call_pattern, single_text)

            if not function_calls:
                return single_text

            for call_args in function_calls:
                # Assuming the first argument is the function name
                function_name = call_args.split(',')[0].strip().strip("'\"")
                try:
                    transformed_text = StringProcessor.call_user_function(call_args,
                                                                        tools_path,
                                                                        context_data_str)
                    if agent_config and agent_config.get('add_dispatch'):
                        function_name = call_args.split(',')[0].strip().strip("'\"")
                        captured_results[function_name] = transformed_text
                    if transformed_text is None:
                        transformed_text = "Error: No valid return from function."
                    single_text = single_text.replace(f"dispatch_task({call_args})",
                                                    transformed_text,
                                                    1)
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
