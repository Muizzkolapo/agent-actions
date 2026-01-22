"""Type definitions for agent configuration structures."""

from typing import TypedDict, Optional, List, Dict, Any


class AgentEntryDict(TypedDict, total=False):
    """Typed representation of a single agent configuration entry."""

    agent_type: str
    name: Optional[str]
    model_name: Optional[str]
    # Model vendor/provider: "openai", "gemini", "anthropic", "groq", or "tool"
    model_vendor: Optional[str]
    api_key: Optional[str]
    code_path: Optional[str]
    dependencies: List[str]
    prompt: Optional[str]
    schema_name: Optional[str]
    chunk_config: Dict[str, Any]
    is_operational: bool
    conditional_clause: Optional[str]
    where_clause: Optional[Dict[str, Any]]
    skip_if: Optional[str]
    ephemeral: Optional[bool]
    add_dispatch: Optional[bool]
    # Anthropic-specific configuration options
    # API version header for Anthropic requests (e.g., "2023-06-01")
    anthropic_version: Optional[str]
    # Enable Anthropic's prompt caching feature for improved performance
    enable_prompt_caching: Optional[bool]
    # Control field flow: observe (LLM context), drop (block), passthrough (output)
    context_scope: Optional[Dict[str, List[str]]]


# Alias for the list of agent entries under a pipeline name
AgentConfigList = List[AgentEntryDict]

# Alias for the mapping of pipeline/agent name to its configuration list
AgentConfigMap = Dict[str, AgentConfigList]
