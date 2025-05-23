import json
from typing import Dict, Any, Optional, List, Union

# vendor handlers
from agent_actions.vendors.openai_vendor     import OpenAIHandler
from agent_actions.vendors.ollama_vendor     import OllamaHandler   # ← NEW
from agent_actions.vendors.gemini_vendor     import GeminiHandler
from agent_actions.vendors.cohere_vendor     import CohereHandler
from agent_actions.vendors.mistral_vendor    import MistralHandler
from agent_actions.vendors.anthropic_vendor  import ClaudeHandler
from agent_actions.vendors.groq_llama        import GroqLlama3Handler
from agent_actions.vendors.deepseek_vendor   import DeepSeekHandler
from agent_actions.vendors.tools_vendor      import ToolHandler

from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.handlers.schema_handler         import SchemaLoader
from agent_actions.handlers.prompt_handler         import PromptLoader
from agent_actions.models.schema_change            import compile_unified_schema
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils


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
    source_content: Optional[Any] = None # Add source_content parameter
) -> List[Any]:
    """
    Build and execute a prompt against the selected vendor, returning
    the model’s response(s) as a list.
    """
    # ----- prompt selection / templating ----------------------------------
    prompt_config_base = _prepare_prompt(agent_config, formatted_prompt)
    if not tools_path:
        tools_path = agent_config.get('tools', {}).get('path')

    model_vendor = agent_config.get("model_vendor", "").lower()
    is_tool      = model_vendor == "tool"

    # Convert context-data to a JSON string unless the vendor is 'tool'
    context_data: Union[str, Dict] = (
        context_data_str if is_tool
        else (json.dumps(context_data_str, ensure_ascii=False)
              if not isinstance(context_data_str, str) else context_data_str)
    )

    # Inject user-defined function outputs into the prompt, if any 
    prompt_config = PromptUtils.inject_function_outputs_into_prompt(
        prompt_config_base,
        tools_path,
        context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False)
    )
    

    _debug_print_prompt(
        agent_config,
        prompt_config,
        context_data if isinstance(context_data, str) else json.dumps(context_data, ensure_ascii=False)
    )

    # ----- schema prep ----------------------------------------------------
    schema       = _prepare_schema(agent_config, model_vendor)
    granularity  = agent_config.get('granularity', 'record').lower()

    # ----- dispatch to vendor handler ------------------------------------
    return _invoke_vendor_handler(
        model_vendor, agent_config, prompt_config,
        context_data, schema, granularity, formatted_prompt,
        tool_args, source_content # Pass tool_args and source_content
    )

# ---------------------------------------------------------------------------
# 3. helpers
# ---------------------------------------------------------------------------

def _prepare_prompt(agent_config: Dict[str, Any], formatted_prompt: Optional[str]) -> str:
    """Return an actual prompt string—either the pre-formatted one or the
    prompt loaded from disk."""
    if formatted_prompt is not None:
        return formatted_prompt

    prompt_cfg = agent_config.get('prompt', '')
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
    schema_name = agent_config.get('schema_name') if model_vendor != 'tool' else None
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
