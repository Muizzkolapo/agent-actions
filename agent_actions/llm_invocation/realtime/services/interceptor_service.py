"""Interceptor execution service for agent builder."""

import json
import sys
from typing import Dict, Any, Optional, List, Union
from agent_actions.prompt_generation.prompt_utils import PromptUtils
from agent_actions.utilities.constants import MODEL_VENDOR_KEY
from .prompt_service import PromptService
from .context_service import ContextService
from .schema_service import SchemaService
from .vendor_invocation_service import VendorInvocationService


class InterceptorService:
    """Handles interceptor pipeline execution with validation and reprompting."""

    @staticmethod
    def execute_with_interceptors(
        agent_config: Dict[str, Any],
        udf: Any,
        context_data_str: Union[str, Dict],
        formatted_prompt: Optional[str],
        tools_path: Optional[str],
        tool_args: Optional[Dict[str, Any]],
        source_content: Optional[Any],
        interceptor_configs: List[Dict[str, Any]],
        additional_context: Optional[Dict] = None,
        original_context: Optional[Union[str, Dict]] = None
    ) -> List[Any]:
        """
        Execute the agent with validation and reprompt interceptors.

        Implements a retry loop that:
        1. Validates responses using non-reprompt interceptors
        2. If validation fails, uses reprompt interceptor to modify prompt
        3. Retries with modified prompt up to max_attempts
        4. Returns successful response or failed response after max attempts

        Args:
            agent_config: Agent configuration with interceptor settings
            udf: User defined function (agent_name) - currently unused
            context_data_str: Context data for LLM (may be transformed)
            formatted_prompt: Pre-formatted prompt (optional)
            tools_path: Path to tool functions (optional)
            tool_args: Tool arguments (optional)
            source_content: Source content for tool handler (optional)
            interceptor_configs: List of interceptor configurations
            additional_context: Additional context from context_scope.observe (optional)
            original_context: Original untransformed context for tools (optional)

        Returns:
            List of response items from the LLM
        """
        # Lazy imports to avoid circular dependencies
        from agent_actions.response_processing.factory import InterceptorFactory
        from agent_actions.prompt_generation.reprompt_interceptor import RepromptInterceptor

        # Separate interceptors by type
        non_reprompt_configs: List[Dict[str, Any]] = [
            cfg for cfg in interceptor_configs
            if cfg.get('type') != 'reprompt'
        ]
        reprompt_cfg = next(
            (cfg for cfg in interceptor_configs if cfg.get('type') == 'reprompt'),
            None
        )

        # Propagate prompt_debug to all interceptors
        prompt_debug = agent_config.get('prompt_debug', False)
        non_reprompt_configs = [
            {**cfg, 'prompt_debug': prompt_debug}
            for cfg in non_reprompt_configs
        ]
        if reprompt_cfg:
            reprompt_cfg = {**reprompt_cfg, 'prompt_debug': prompt_debug}

        # Build interceptor chain
        interceptors = InterceptorFactory.build_chain(non_reprompt_configs)
        reprompt_interceptor: Optional[RepromptInterceptor] = (
            InterceptorFactory.create_interceptor(reprompt_cfg)
            if reprompt_cfg else None
        )

        # Parse context_data_str for execution context
        parsed_context_data = {}
        if isinstance(context_data_str, str):
            try:
                parsed_context_data = json.loads(context_data_str)
            except (json.JSONDecodeError, TypeError):
                parsed_context_data = {}
        elif isinstance(context_data_str, dict):
            parsed_context_data = context_data_str

        # Initialize execution context for retry loop
        execution_context: Dict[str, Any] = {
            'prompt': formatted_prompt or agent_config.get('prompt', ''),
            'original_prompt': formatted_prompt or agent_config.get('prompt', ''),
            'attempt': 0,
            'agent_config': agent_config,
            'history': [],
            **parsed_context_data
        }

        # Get max_attempts from reprompt config
        max_attempts = 3  # default
        if reprompt_cfg:
            max_attempts = (
                reprompt_cfg.get('max_attempts')
                or reprompt_cfg.get('config', {}).get('max_attempts', 3)
            )

        # Retry loop with safety counter
        safety_counter = 0
        while execution_context['attempt'] < max_attempts and safety_counter < 10:
            safety_counter += 1

            if prompt_debug:
                print(
                    f"🔄 RETRY LOOP: attempt={execution_context['attempt']}, "
                    f"safety_counter={safety_counter}"
                )
                print(
                    f"   validation_error present: "
                    f"{bool(execution_context.get('validation_error'))}"
                )

            # Handle reprompting if validation failed
            if reprompt_interceptor and execution_context.get('validation_error'):
                reprompt_result = reprompt_interceptor.intercept(
                    None,
                    execution_context
                )

                # Check if max attempts reached
                if (reprompt_result.metadata
                        and reprompt_result.metadata.get('max_attempts_reached')):
                    return execution_context.get('failed_response', [])

                # Update execution context with retry context
                if reprompt_result.retry_context:
                    execution_context.update(reprompt_result.retry_context)

                # Clear validation error flags
                execution_context.pop('validation_error', None)
                execution_context.pop('validator_name', None)
                execution_context.pop('validator_args', None)
                execution_context.pop('failed_response', None)

            # Get current prompt from execution context
            current_prompt = execution_context.get('prompt')

            # Setup tools_path using shared utility
            if not tools_path:
                from agent_actions.utilities.tools_resolver import resolve_tools_path
                tools_path = resolve_tools_path(agent_config)
            if tools_path and tools_path not in sys.path:
                sys.path.insert(0, tools_path)

            # Get model vendor and check if tool
            model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or '').lower()
            is_tool = model_vendor == 'tool'

            # Prepare context data (critical: preserve context separation)
            context_data = ContextService.prepare_context_data(
                context_data_str,
                original_context,
                is_tool
            )

            # IMPORTANT: formatted_prompt MUST be prepared using PromptPreparationService
            # dispatch_task() injection now happens in PromptPreparationService
            if formatted_prompt is None:
                raise ValueError(
                    "formatted_prompt is required. "
                    "Please use PromptPreparationService.prepare_prompt_with_context() "
                    "to prepare the prompt before calling execute_with_interceptors(). "
                    "See agent_actions/prompt_generation/data_generator.py for an example."
                )

            # Use the prompt directly (dispatch already injected)
            prompt_config = current_prompt

            # TODO: captured_results (add_dispatch feature) needs to be returned from PromptPreparationService
            captured_results = {}

            # Append additional_context if provided (context_scope.observe fields)
            if additional_context:
                from agent_actions.utilities.context_scope.context_scope_processor import (
                    ContextScopeProcessor
                )
                context_msg = ContextScopeProcessor.format_llm_context(
                    additional_context
                )
                if context_msg:
                    prompt_config = f"{prompt_config}\n\n{context_msg}"

            # Debug print
            PromptService.debug_print_prompt(
                agent_config,
                prompt_config,
                (context_data if isinstance(context_data, str)
                 else json.dumps(context_data, ensure_ascii=False))
            )

            # Prepare schema
            schema = SchemaService.prepare_schema(agent_config, model_vendor)

            # Get granularity
            granularity = (agent_config.get('granularity') or 'record').lower()

            # Invoke vendor
            response_data = VendorInvocationService.invoke_vendor(
                model_vendor,
                agent_config,
                prompt_config,
                context_data,
                schema,
                granularity,
                current_prompt,
                tool_args,
                source_content
            )

            # Merge captured results if any
            if captured_results:
                for item in response_data:
                    if isinstance(item, dict):
                        item.update(captured_results)

            if prompt_debug:
                print('   Processing response through interceptors...')
                print(f'   Response data type: {type(response_data)}')
                print(f'   Response preview: {str(response_data)[:200]}')

            # Process through validation interceptors
            result = interceptors.process(response_data, execution_context)

            if prompt_debug:
                print(
                    f'   Interceptor result: '
                    f'retry_context={bool(result.retry_context)}'
                )

            # If validation failed, update context and retry
            if result.retry_context:
                if prompt_debug:
                    print(f'   Retry context keys: {list(result.retry_context.keys())}')
                execution_context.update(result.retry_context)
                if prompt_debug:
                    print(
                        f"   Updated execution context attempt: "
                        f"{execution_context.get('attempt')}"
                    )
                continue

            # Validation passed, return successful response
            if prompt_debug:
                print('   ✅ Returning successful response')

            return result.modified_response or response_data

        # Exhausted all attempts, return last response
        return response_data
