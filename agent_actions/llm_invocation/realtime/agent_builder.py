import json
import sys
from typing import Dict, Any, Optional, List, Union
from agent_actions.llm_invocation.realtime.providers.openai.vendor import OpenAIHandler
from agent_actions.llm_invocation.realtime.providers.ollama.vendor import OllamaHandler
from agent_actions.llm_invocation.realtime.providers.gemini.vendor import GeminiHandler
from agent_actions.llm_invocation.realtime.providers.cohere.vendor import CohereHandler
from agent_actions.llm_invocation.realtime.providers.mistral.vendor import MistralHandler
from agent_actions.llm_invocation.realtime.providers.anthropic.vendor import ClaudeHandler
from agent_actions.llm_invocation.realtime.providers.groq.vendor import GroqLlama3Handler
from agent_actions.llm_invocation.realtime.providers.deepseek.vendor import DeepSeekHandler
from agent_actions.llm_invocation.realtime.providers.tools.vendor import ToolHandler
from agent_actions.prompt_generation.prompt_handler import PromptLoader
from agent_actions.preprocessing.prompt_utils import PromptUtils
from agent_actions.utilities.constants import MODEL_VENDOR_KEY, PROMPT_KEY
VENDOR_HANDLERS: dict[str, Any] = {'openai': OpenAIHandler, 'ollama': OllamaHandler, 'gemini': GeminiHandler, 'cohere': CohereHandler, 'mistral': MistralHandler, 'anthropic': ClaudeHandler, 'groq': GroqLlama3Handler, 'deepseek': DeepSeekHandler, 'tool': ToolHandler}
SINGLE_RESPONSE_VENDORS: set[str] = {'cohere', 'mistral', 'anthropic', 'groq', 'deepseek'}

def create_dynamic_agent(agent_config: Dict[str, Any], udf: Any, context_data_str: Union[str, Dict], formatted_prompt: Optional[str]=None, tools_path: Optional[str]=None, tool_args: Optional[Dict[str, Any]]=None, source_content: Optional[Any]=None, additional_context: Optional[Dict]=None) -> List[Any]:
    """Build and execute a prompt against the selected vendor.

    If the agent configuration specifies response interceptors, the request
    will be executed through the interceptor pipeline which can validate and
    reprompt on failure.

    Args:
        agent_config: Agent configuration with model/prompt settings
        udf: User defined function (agent_name)
        context_data_str: Context data as string or dict
        formatted_prompt: Pre-formatted prompt (optional, from DataGenerator)
        tools_path: Path to tool functions (optional)
        tool_args: Tool arguments (optional)
        source_content: Source content for tool handler (optional)
        additional_context: Additional context from context_scope.observe (optional).
                           Formatted and appended to prompt before LLM invocation.

    Returns:
        List of response items from the LLM
    """
    interceptor_configs = agent_config.get('interceptors', [])
    if interceptor_configs:
        return _execute_with_interceptors(agent_config, udf, context_data_str, formatted_prompt, tools_path, tool_args, source_content, interceptor_configs, additional_context)
    prompt_config_base = _prepare_prompt(agent_config, formatted_prompt)
    if not tools_path:
        tools_path = agent_config.get('tools', {}).get('path')
    if tools_path and tools_path not in sys.path:
        sys.path.insert(0, tools_path)
    model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or '').lower()
    is_tool = model_vendor == 'tool'
    context_data: Union[str, Dict] = context_data_str if is_tool else json.dumps(context_data_str, ensure_ascii=False) if not isinstance(context_data_str, str) else context_data_str

    # Only process field references if prompt wasn't pre-formatted
    # When formatted_prompt is provided, it's already been processed by DataGenerator
    if formatted_prompt is None:
        field_context = _build_field_context_from_context_data(context_data_str, agent_config)
        if field_context:
            prompt_config_base = PromptUtils.replace_field_references(prompt_config_base, field_context)

    prompt_config, captured_results = PromptUtils.inject_function_outputs_into_prompt(prompt_config_base, tools_path, context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False), agent_config=agent_config)

    # Append additional_context to prompt if provided (context_scope.observe fields)
    if additional_context:
        from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
        print(f"\n[DEBUG agent_builder] Received additional_context: {list(additional_context.keys())}")
        context_msg = ContextScopeProcessor.format_llm_context(additional_context)
        print(f"[DEBUG agent_builder] Formatted message length: {len(context_msg) if context_msg else 0}")
        if context_msg:
            prompt_config = f"{prompt_config}\n\n{context_msg}"
            print(f"[DEBUG agent_builder] ✅ Additional context appended to prompt")
        else:
            print(f"[DEBUG agent_builder] ❌ context_msg is empty!")
    else:
        print(f"\n[DEBUG agent_builder] No additional_context received")

    _debug_print_prompt(agent_config, prompt_config, context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False))
    schema = _prepare_schema(agent_config, model_vendor)
    granularity = (agent_config.get('granularity') or 'record').lower()
    response_data = _invoke_vendor_handler(model_vendor, agent_config, prompt_config, context_data, schema, granularity, formatted_prompt, tool_args, source_content)
    if captured_results:
        for item in response_data:
            if isinstance(item, dict):
                item.update(captured_results)
    return response_data

def _prepare_prompt(agent_config: Dict[str, Any], formatted_prompt: Optional[str]) -> str:
    """Return an actual prompt string—either the pre-formatted one or the
    prompt loaded from disk."""
    if formatted_prompt is not None:
        return formatted_prompt
    prompt_cfg = agent_config.get(PROMPT_KEY, '')
    if isinstance(prompt_cfg, str) and prompt_cfg.startswith('$'):
        return PromptLoader.load_prompt(prompt_cfg[1:])
    return prompt_cfg

def _build_field_context_from_context_data(context_data: Union[str, Dict], agent_config: Dict) -> Optional[Dict]:
    """
    Build field_context dict from context_data for field reference replacement.

    In agent_builder, we don't have the full dependency graph like DataGenerator,
    but we can build a basic field_context from available data.

    Args:
        context_data: The context data (str or dict)
        agent_config: Agent configuration

    Returns:
        field_context dict or None

    Example:
        Input: context_data = '{"page_content": "Hello", "title": "Test"}'
        Output: {'source': {'page_content': 'Hello', 'title': 'Test'}}
    """
    if isinstance(context_data, str):
        try:
            parsed = json.loads(context_data)
        except (json.JSONDecodeError, TypeError):
            return None
    elif isinstance(context_data, dict):
        parsed = context_data
    else:
        return None
    return {'source': parsed}

def _debug_print_prompt(agent_config: Dict[str, Any], prompt_config: str, context_data: str='') -> None:
    if agent_config.get('prompt_debug', False):
        divider = '=' * 50
        print(f'\n{divider}\nDEBUG MODE: Prompt being sent to the agent\n{divider}')
        print(prompt_config)
        if context_data:
            print('\n[Context Data Preview]\n' + '-' * 50)
            print(context_data)
        print(f'{divider}\n')

def _prepare_schema(agent_config: Dict[str, Any], model_vendor: str) -> Optional[Dict[str, Any]]:
    """
    Prepare schema for the given vendor.

    Uses the unified prepare_schema_unified() function to ensure consistent
    schema handling across online and batch modes.
    """
    from agent_actions.response_processing.schema_change import prepare_schema_unified
    return prepare_schema_unified(agent_config, model_vendor)

def _invoke_vendor_handler(model_vendor: str, agent_config: Dict[str, Any], prompt_config: str, context_data: Union[str, Dict], schema: Optional[Dict[str, Any]], granularity: str, formatted_prompt: Optional[str]=None, tool_args: Optional[Dict[str, Any]]=None, source_content: Optional[Any]=None) -> List[Any]:
    """Delegates to the specific vendor handler and normalises the response."""
    if model_vendor not in VENDOR_HANDLERS:
        raise ValueError(f'Unsupported model vendor: {model_vendor}')
    handler = VENDOR_HANDLERS[model_vendor]
    if model_vendor == 'groq':
        response_data = handler.invoke(agent_config, formatted_prompt, context_data, schema)
    elif model_vendor == 'tool':
        response_data = handler.invoke(agent_config, context_data, tool_args=tool_args, source_content=source_content)
        if granularity == 'file':
            return response_data
    else:
        response_data = handler.invoke(agent_config, prompt_config, context_data, schema)
    if model_vendor in SINGLE_RESPONSE_VENDORS:
        return [response_data]
    return response_data

def _execute_with_interceptors(agent_config: Dict[str, Any], udf: Any, context_data_str: Union[str, Dict], formatted_prompt: Optional[str], tools_path: Optional[str], tool_args: Optional[Dict[str, Any]], source_content: Optional[Any], interceptor_configs: List[Dict[str, Any]], additional_context: Optional[Dict]=None) -> List[Any]:
    """Execute the agent with validation and reprompt interceptors."""
    from agent_actions.response_processing.factory import InterceptorFactory
    from agent_actions.prompt_generation.reprompt_interceptor import RepromptInterceptor
    non_reprompt_configs: List[Dict[str, Any]] = [cfg for cfg in interceptor_configs if cfg.get('type') != 'reprompt']
    reprompt_cfg = next((cfg for cfg in interceptor_configs if cfg.get('type') == 'reprompt'), None)
    prompt_debug = agent_config.get('prompt_debug', False)
    non_reprompt_configs = [{**cfg, 'prompt_debug': prompt_debug} for cfg in non_reprompt_configs]
    if reprompt_cfg:
        reprompt_cfg = {**reprompt_cfg, 'prompt_debug': prompt_debug}
    interceptors = InterceptorFactory.build_chain(non_reprompt_configs)
    reprompt_interceptor: RepromptInterceptor | None = InterceptorFactory.create_interceptor(reprompt_cfg) if reprompt_cfg else None
    parsed_context_data = {}
    if isinstance(context_data_str, str):
        try:
            parsed_context_data = json.loads(context_data_str)
        except (json.JSONDecodeError, TypeError):
            parsed_context_data = {}
    elif isinstance(context_data_str, dict):
        parsed_context_data = context_data_str
    execution_context: Dict[str, Any] = {'prompt': formatted_prompt or agent_config.get('prompt', ''), 'original_prompt': formatted_prompt or agent_config.get('prompt', ''), 'attempt': 0, 'agent_config': agent_config, 'history': [], **parsed_context_data}
    max_attempts = 3
    if reprompt_cfg:
        max_attempts = reprompt_cfg.get('max_attempts') or reprompt_cfg.get('config', {}).get('max_attempts', 3)
    safety_counter = 0
    while execution_context['attempt'] < max_attempts and safety_counter < 10:
        safety_counter += 1
        if prompt_debug:
            print(f"🔄 RETRY LOOP: attempt={execution_context['attempt']}, safety_counter={safety_counter}")
            print(f"   validation_error present: {bool(execution_context.get('validation_error'))}")
        if reprompt_interceptor and execution_context.get('validation_error'):
            reprompt_result = reprompt_interceptor.intercept(None, execution_context)
            if reprompt_result.metadata and reprompt_result.metadata.get('max_attempts_reached'):
                return execution_context.get('failed_response', [])
            if reprompt_result.retry_context:
                execution_context.update(reprompt_result.retry_context)
            execution_context.pop('validation_error', None)
            execution_context.pop('validator_name', None)
            execution_context.pop('validator_args', None)
            execution_context.pop('failed_response', None)
        current_prompt = execution_context.get('prompt')
        prompt_config_base = _prepare_prompt(agent_config, current_prompt)
        if not tools_path:
            tools_path = agent_config.get('tools', {}).get('path')
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, tools_path)
        model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or '').lower()
        is_tool = model_vendor == 'tool'
        context_data: Union[str, Dict] = context_data_str if is_tool else json.dumps(context_data_str, ensure_ascii=False) if not isinstance(context_data_str, str) else context_data_str

        # Only process field references if prompt wasn't pre-formatted
        # When formatted_prompt is provided, it's already been processed by DataGenerator
        if formatted_prompt is None:
            field_context = _build_field_context_from_context_data(context_data_str, agent_config)
            if field_context:
                prompt_config_base = PromptUtils.replace_field_references(prompt_config_base, field_context)

        prompt_config, captured_results = PromptUtils.inject_function_outputs_into_prompt(prompt_config_base, tools_path, context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False), agent_config=agent_config)

        # Append additional_context to prompt if provided (context_scope.observe fields)
        if additional_context:
            from agent_actions.utilities.context_scope_processor import ContextScopeProcessor
            context_msg = ContextScopeProcessor.format_llm_context(additional_context)
            if context_msg:
                prompt_config = f"{prompt_config}\n\n{context_msg}"

        _debug_print_prompt(agent_config, prompt_config, context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False))
        schema = _prepare_schema(agent_config, model_vendor)
        granularity = (agent_config.get('granularity') or 'record').lower()
        response_data = _invoke_vendor_handler(model_vendor, agent_config, prompt_config, context_data, schema, granularity, current_prompt, tool_args, source_content)
        if captured_results:
            for item in response_data:
                if isinstance(item, dict):
                    item.update(captured_results)
        if prompt_debug:
            print(f'   Processing response through interceptors...')
            print(f'   Response data type: {type(response_data)}')
            print(f'   Response preview: {str(response_data)[:200]}')
        result = interceptors.process(response_data, execution_context)
        if prompt_debug:
            print(f'   Interceptor result: retry_context={bool(result.retry_context)}')
        if result.retry_context:
            if prompt_debug:
                print(f'   Retry context keys: {list(result.retry_context.keys())}')
            execution_context.update(result.retry_context)
            if prompt_debug:
                print(f"   Updated execution context attempt: {execution_context.get('attempt')}")
            continue
        if prompt_debug:
            print(f'   ✅ Returning successful response')
        return result.modified_response or response_data
    return response_data