import json
import sys
from typing import Dict, Any, Optional, List, Union

# vendor handlers
from agent_actions.integrations.providers.openai.vendor     import OpenAIHandler
from agent_actions.integrations.providers.ollama.vendor     import OllamaHandler   # ← NEW
from agent_actions.integrations.providers.gemini.vendor     import GeminiHandler
from agent_actions.integrations.providers.cohere.vendor     import CohereHandler
from agent_actions.integrations.providers.mistral.vendor    import MistralHandler
from agent_actions.integrations.providers.anthropic.vendor  import ClaudeHandler
from agent_actions.integrations.providers.groq.vendor        import GroqLlama3Handler
from agent_actions.integrations.providers.deepseek.vendor   import DeepSeekHandler
from agent_actions.integrations.providers.tools.vendor      import ToolHandler

from agent_actions.agents.handlers.schema_handler         import SchemaLoader
from agent_actions.agents.handlers.prompt_handler         import PromptLoader
from agent_actions.core.parser.schema_change            import compile_unified_schema
from agent_actions.agents.transformers.prompt_utils import PromptUtils
from agent_actions.core.constants import (
    MODEL_VENDOR_KEY,
    PROMPT_KEY,
    SCHEMA_NAME_KEY,
    SCHEMA_KEY,
)


# ---------------------------------------------------------------------------
# 1. dispatch tables
# ---------------------------------------------------------------------------

VENDOR_HANDLERS: dict[str, Any] = {
    'openai'   : OpenAIHandler,
    'ollama'   : OllamaHandler,           # ← NEW
    'gemini'   : GeminiHandler,
    'cohere'   : CohereHandler,
    'mistral'  : MistralHandler,
    'anthropic': ClaudeHandler,
    'groq'     : GroqLlama3Handler,
    'deepseek' : DeepSeekHandler,
    'tool'     : ToolHandler,
}

# Vendors whose raw return value is a single element; we wrap it in a list
SINGLE_RESPONSE_VENDORS: set[str] = {
    'cohere', 'mistral', 'anthropic', 'groq', 'deepseek'
    # openai & ollama both return whatever your schema dictates (obj or list)
}

# Vendors for which we pre-compile a “unified” schema
SCHEMA_COMPILATION_VENDORS: set[str] = {
    'openai', 'anthropic', 'gemini', 'ollama'   # ← NEW
}

# ---------------------------------------------------------------------------
# 2. public entry-point
# ---------------------------------------------------------------------------

def create_dynamic_agent(
    agent_config: Dict[str, Any],
    udf: Any,
    context_data_str: Union[str, Dict],
    formatted_prompt: Optional[str] = None,
    tools_path: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    source_content: Optional[Any] = None  # Add source_content parameter
) -> List[Any]:
    """Build and execute a prompt against the selected vendor.

    If the agent configuration specifies response interceptors, the request
    will be executed through the interceptor pipeline which can validate and
    reprompt on failure.
    """
    interceptor_configs = agent_config.get("interceptors", [])
    if interceptor_configs:
        return _execute_with_interceptors(
            agent_config,
            udf,
            context_data_str,
            formatted_prompt,
            tools_path,
            tool_args,
            source_content,
            interceptor_configs,
        )

    # ----- prompt selection / templating ----------------------------------
    prompt_config_base = _prepare_prompt(agent_config, formatted_prompt)
    if not tools_path:
        tools_path = agent_config.get('tools', {}).get('path')
    if tools_path and tools_path not in sys.path:
        sys.path.insert(0, tools_path)

    model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or "").lower()
    is_tool      = model_vendor == "tool"

    # Convert context-data to a JSON string unless the vendor is 'tool'
    context_data: Union[str, Dict] = (
        context_data_str if is_tool
        else (json.dumps(context_data_str, ensure_ascii=False)
              if not isinstance(context_data_str, str) else context_data_str)
    )

    # Inject user-defined function outputs into the prompt, if any
    prompt_config, captured_results = PromptUtils.inject_function_outputs_into_prompt(
        prompt_config_base,
        tools_path,
        context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False),
        agent_config=agent_config
    )

    _debug_print_prompt(
        agent_config,
        prompt_config,
        context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False)
    )

    # ----- schema prep ----------------------------------------------------
    schema = _prepare_schema(agent_config, model_vendor)
    granularity = (agent_config.get('granularity') or 'record').lower()

    # ----- dispatch to vendor handler ------------------------------------
    response_data = _invoke_vendor_handler(
        model_vendor, agent_config, prompt_config,
        context_data, schema, granularity, formatted_prompt,
        tool_args, source_content
    )

    # If there are captured results, add them to the response
    if captured_results:
        # This assumes response_data is a list of dictionaries
        for item in response_data:
            if isinstance(item, dict):
                item.update(captured_results)

    return response_data

# ---------------------------------------------------------------------------
# 3. helpers
# ---------------------------------------------------------------------------

def _prepare_prompt(agent_config: Dict[str, Any], formatted_prompt: Optional[str]) -> str:
    """Return an actual prompt string—either the pre-formatted one or the
    prompt loaded from disk."""
    if formatted_prompt is not None:
        return formatted_prompt

    prompt_cfg = agent_config.get(PROMPT_KEY, '')
    if isinstance(prompt_cfg, str) and prompt_cfg.startswith('$'):
        return PromptLoader.load_prompt(prompt_cfg[1:])
    


    return prompt_cfg


def _debug_print_prompt(agent_config: Dict[str, Any], prompt_config: str, context_data: str = "") -> None:
    if agent_config.get('prompt_debug', False):
        divider = "=" * 50
        print(f"\n{divider}\nDEBUG MODE: Prompt being sent to the agent\n{divider}")
        print(prompt_config)
        if context_data:
            print("\n[Context Data Preview]\n" + "-" * 50)
            print(context_data)
        print(f"{divider}\n")


def _prepare_schema(agent_config: Dict[str, Any], model_vendor: str) -> Optional[Dict[str, Any]]:
    # Check for inline schema first
    inline_schema = agent_config.get(SCHEMA_KEY) if model_vendor != 'tool' else None
    if inline_schema:
        # Construct unified schema from the inline dictionary
        base_schema = SchemaLoader.construct_schema_from_dict(inline_schema)
        return (compile_unified_schema(base_schema, model_vendor)
                if model_vendor in SCHEMA_COMPILATION_VENDORS else base_schema)
    
    # Fall back to schema_name if no inline schema
    schema_name = agent_config.get(SCHEMA_NAME_KEY) if model_vendor != 'tool' else None
    if not schema_name:
        return None

    base_schema = SchemaLoader.load_schema(schema_name)
    return (compile_unified_schema(base_schema, model_vendor)
            if model_vendor in SCHEMA_COMPILATION_VENDORS else base_schema)


def _invoke_vendor_handler(
    model_vendor: str,
    agent_config: Dict[str, Any],
    prompt_config: str,
    context_data: Union[str, Dict],
    schema: Optional[Dict[str, Any]],
    granularity: str,
    formatted_prompt: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    source_content: Optional[Any] = None # Add source_content parameter
) -> List[Any]:
    """Delegates to the specific vendor handler and normalises the response."""
    if model_vendor not in VENDOR_HANDLERS:
        raise ValueError(f"Unsupported model vendor: {model_vendor}")

    handler = VENDOR_HANDLERS[model_vendor]

    # GroqLlama3 uses the preformatted prompt argument
    if model_vendor == 'groq':
        response_data = handler.invoke(agent_config, formatted_prompt, context_data, schema)

    # ToolHandler ignores prompt_config entirely
    elif model_vendor == 'tool':
        response_data = handler.invoke(
            agent_config,
            context_data,
            tool_args=tool_args,
            source_content=source_content # Pass source_content to ToolHandler
        )
        if granularity == 'file':      # file-level content goes straight out
            return response_data

    # All other vendors—including OpenAI & Ollama—use the default signature
    else:
        response_data = handler.invoke(agent_config, prompt_config, context_data, schema)

    # Normalise single-element responses
    if model_vendor in SINGLE_RESPONSE_VENDORS:
        return [response_data]

    return response_data


def _execute_with_interceptors(
    agent_config: Dict[str, Any],
    udf: Any,
    context_data_str: Union[str, Dict],
    formatted_prompt: Optional[str],
    tools_path: Optional[str],
    tool_args: Optional[Dict[str, Any]],
    source_content: Optional[Any],
    interceptor_configs: List[Dict[str, Any]],
) -> List[Any]:
    """Execute the agent with validation and reprompt interceptors."""

    from agent_actions.integrations.interceptors.factory import InterceptorFactory
    from agent_actions.integrations.interceptors.reprompt_interceptor import RepromptInterceptor

    # Separate reprompt interceptor from others
    non_reprompt_configs: List[Dict[str, Any]] = [
        cfg for cfg in interceptor_configs if cfg.get("type") != "reprompt"
    ]
    reprompt_cfg = next(
        (cfg for cfg in interceptor_configs if cfg.get("type") == "reprompt"),
        None,
    )

    # Add prompt_debug to all interceptor configs without mutating original
    prompt_debug = agent_config.get('prompt_debug', False)
    
    # Create copies with prompt_debug added
    non_reprompt_configs = [
        {**cfg, 'prompt_debug': prompt_debug} for cfg in non_reprompt_configs
    ]
    if reprompt_cfg:
        reprompt_cfg = {**reprompt_cfg, 'prompt_debug': prompt_debug}
    
    interceptors = InterceptorFactory.build_chain(non_reprompt_configs)
    reprompt_interceptor: RepromptInterceptor | None = (
        InterceptorFactory.create_interceptor(reprompt_cfg) if reprompt_cfg else None
    )

    # Parse context data to make it accessible to interceptors
    parsed_context_data = {}
    if isinstance(context_data_str, str):
        try:
            parsed_context_data = json.loads(context_data_str)
        except (json.JSONDecodeError, TypeError):
            parsed_context_data = {}
    elif isinstance(context_data_str, dict):
        parsed_context_data = context_data_str

    execution_context: Dict[str, Any] = {
        "prompt": formatted_prompt or agent_config.get("prompt", ""),
        "original_prompt": formatted_prompt or agent_config.get("prompt", ""),
        "attempt": 0,
        "agent_config": agent_config,
        "history": [],
        # Add record context data so interceptors can access workflow data
        **parsed_context_data,
    }

    max_attempts = 3
    if reprompt_cfg:
        # Check both flat structure and nested config structure
        max_attempts = reprompt_cfg.get("max_attempts") or reprompt_cfg.get("config", {}).get("max_attempts", 3)

    safety_counter = 0  # Add safety counter to prevent infinite loops
    while execution_context["attempt"] < max_attempts and safety_counter < 10:
        safety_counter += 1
        if prompt_debug:
            print(f"🔄 RETRY LOOP: attempt={execution_context['attempt']}, safety_counter={safety_counter}")
            print(f"   validation_error present: {bool(execution_context.get('validation_error'))}")
        
        # Generate improved prompt if previous validation failed
        if reprompt_interceptor and execution_context.get("validation_error"):
            reprompt_result = reprompt_interceptor.intercept(None, execution_context)
            if reprompt_result.metadata and reprompt_result.metadata.get(
                "max_attempts_reached"
            ):
                return execution_context.get("failed_response", [])
            if reprompt_result.retry_context:
                execution_context.update(reprompt_result.retry_context)
            # Clear validation error before next attempt
            execution_context.pop("validation_error", None)
            execution_context.pop("validator_name", None)
            execution_context.pop("validator_args", None)
            execution_context.pop("failed_response", None)

        current_prompt = execution_context.get("prompt")

        prompt_config_base = _prepare_prompt(agent_config, current_prompt)
        if not tools_path:
            tools_path = agent_config.get("tools", {}).get("path")
        if tools_path and tools_path not in sys.path:
            sys.path.insert(0, tools_path)

        model_vendor = (agent_config.get(MODEL_VENDOR_KEY) or "").lower()
        is_tool = model_vendor == "tool"

        context_data: Union[str, Dict] = (
            context_data_str
            if is_tool
            else (
                json.dumps(context_data_str, ensure_ascii=False)
                if not isinstance(context_data_str, str)
                else context_data_str
            )
        )

        prompt_config, captured_results = PromptUtils.inject_function_outputs_into_prompt(
            prompt_config_base,
            tools_path,
            context_data
            if isinstance(context_data, str)
            else json.dumps(context_data, ensure_ascii=False),
            agent_config=agent_config,
        )

        _debug_print_prompt(
            agent_config,
            prompt_config,
            context_data
            if isinstance(context_data, str)
            else json.dumps(context_data, ensure_ascii=False),
        )

        schema = _prepare_schema(agent_config, model_vendor)
        granularity = (agent_config.get("granularity") or "record").lower()

        response_data = _invoke_vendor_handler(
            model_vendor,
            agent_config,
            prompt_config,
            context_data,
            schema,
            granularity,
            current_prompt,
            tool_args,
            source_content,
        )

        if captured_results:
            for item in response_data:
                if isinstance(item, dict):
                    item.update(captured_results)

        if prompt_debug:
            print(f"   Processing response through interceptors...")
            print(f"   Response data type: {type(response_data)}")
            print(f"   Response preview: {str(response_data)[:200]}")
        
        result = interceptors.process(response_data, execution_context)

        if prompt_debug:
            print(f"   Interceptor result: retry_context={bool(result.retry_context)}")
        if result.retry_context:
            if prompt_debug:
                print(f"   Retry context keys: {list(result.retry_context.keys())}")
            execution_context.update(result.retry_context)
            if prompt_debug:
                print(f"   Updated execution context attempt: {execution_context.get('attempt')}")
            continue

        if prompt_debug:
            print(f"   ✅ Returning successful response")
        return result.modified_response or response_data

    return response_data
