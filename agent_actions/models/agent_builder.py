import json
from typing import Dict, Any, Optional, List, Union

from agent_actions.vendors.openai_vendor import OpenAIHandler
from agent_actions.vendors.gemini_vendor import GeminiHandler
from agent_actions.vendors.cohere_vendor import CohereHandler
from agent_actions.vendors.mistral_vendor import MistralHandler
from agent_actions.vendors.anthropic_vendor import ClaudeHandler
from agent_actions.vendors.groq_llama import GroqLlama3Handler
from agent_actions.vendors.deepseek_vendor import DeepSeekHandler
from agent_actions.vendors.tools_vendor import ToolHandler
from agent_actions.transformers.string_transformer import StringProcessor
from agent_actions.handlers.schema_handler import SchemaLoader
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.models.schema_change import compile_unified_schema
from agent_actions.processors.prompt_processor.prompt_utils import PromptUtils


# Map vendor names to their handler classes for easier extensibility
VENDOR_HANDLERS = {
    'openai': OpenAIHandler,
    'gemini': GeminiHandler,
    'cohere': CohereHandler,
    'mistral': MistralHandler,
    'anthropic': ClaudeHandler,
    'groq': GroqLlama3Handler,
    'deepseek': DeepSeekHandler,
    'tool': ToolHandler
}

# Vendors that return a single response that needs to be wrapped in a list
SINGLE_RESPONSE_VENDORS = {'cohere', 'mistral', 'anthropic', 'groq', 'deepseek'}

# Vendors that support unified schema compilation
SCHEMA_COMPILATION_VENDORS = {'openai', 'anthropic', 'gemini'}


def create_dynamic_agent(
    agent_config: Dict[str, Any],
    udf: Any,
    context_data_str: Union[str, Dict],
    formatted_prompt: Optional[str] = None,
    tools_path: Optional[str] = None
) -> List[Any]:
    """
    Create a dynamic agent based on the provided configuration, with support for transforming the prompt
    using user-defined Python functions specified in the configuration.

    Args:
        agent_config: Configuration for the prompt.
        udf: User-defined functions.
        context_data_str: Input documentation for the agent.
        formatted_prompt: Preformatted prompt if available.
        tools_path: Path to the user's tools directory where custom functions are stored.

    Returns:
        Result of the agent's invocation.

    Raises:
        ValueError: If an unsupported model vendor is specified.
    """
    prompt_config = _prepare_prompt(agent_config, formatted_prompt)
    
    if not tools_path:
        tools_path = agent_config.get('tools', {}).get('path')

    # Convert context data to JSON string if it's not already a string
    context_data = json.dumps(context_data_str) if not isinstance(context_data_str, str) else context_data_str

    # Transform the prompt using custom functions if needed
    transformed_prompt_config = PromptUtils.inject_function_outputs_into_prompt(
        prompt_config, tools_path, context_data
    )
    
    prompt_config = transformed_prompt_config

    _debug_print_prompt(agent_config, prompt_config)

    model_vendor = agent_config['model_vendor'].lower()
    granularity = agent_config.get('granularity', 'record').lower()
    
    # Prepare schema if needed
    schema = _prepare_schema(agent_config, model_vendor)
    
    # Invoke the appropriate handler for the vendor
    return _invoke_vendor_handler(
        model_vendor, agent_config, prompt_config, context_data, schema, granularity, formatted_prompt
    )


def _prepare_prompt(agent_config: Dict[str, Any], formatted_prompt: Optional[str]) -> str:
    """Prepare the prompt from config or use the preformatted one."""
    if formatted_prompt is not None:
        return formatted_prompt
        
    prompt_config = agent_config.get('prompt', '')
    if isinstance(prompt_config, str) and prompt_config.startswith('$'):
        return PromptLoader.load_prompt(prompt_config[1:])
    
    return prompt_config


def _debug_print_prompt(agent_config: Dict[str, Any], prompt_config: str) -> None:
    """Print the prompt for debugging if enabled in config."""
    if agent_config.get('prompt_debug', False):
        print("\n" + "="*40)
        print("DEBUG: Prompt going into the agent:")
        print("="*40)
        print(prompt_config)
        print("="*40 + "\n")


def _prepare_schema(agent_config: Dict[str, Any], model_vendor: str) -> Optional[Dict[str, Any]]:
    """Prepare schema based on the agent configuration and model vendor."""
    schema_name = agent_config.get('schema_name') if model_vendor != 'tool' else None
    
    if not schema_name:
        return None
        
    base_schema = SchemaLoader.load_schema(schema_name)
    
    # Compile the schema based on the model vendor
    if model_vendor in SCHEMA_COMPILATION_VENDORS:
        return compile_unified_schema(base_schema, model_vendor)
    
    return base_schema


def _invoke_vendor_handler(
    model_vendor: str,
    agent_config: Dict[str, Any],
    prompt_config: str,
    context_data: str,
    schema: Optional[Dict[str, Any]],
    granularity: str,
    formatted_prompt: Optional[str] = None
) -> List[Any]:
    """Invoke the appropriate handler for the vendor and format the response."""
    if model_vendor not in VENDOR_HANDLERS:
        raise ValueError(f"Unsupported model vendor: {model_vendor}")
    
    handler = VENDOR_HANDLERS[model_vendor]
    
    # Special case for GroqLlama3Handler which uses formatted_prompt instead of prompt_config
    if model_vendor == 'groq':
        response_data = handler.invoke(agent_config, formatted_prompt, context_data, schema)
    # Special case for ToolHandler which doesn't use prompt_config
    elif model_vendor == 'tool':
        response_data = handler.invoke(agent_config, context_data)
        # Return as is for file granularity
        if granularity == 'file':
            return response_data
    else:
        response_data = handler.invoke(agent_config, prompt_config, context_data, schema)
    
    # Wrap single responses in a list for consistency
    if model_vendor in SINGLE_RESPONSE_VENDORS:
        return [response_data]
    
    return response_data