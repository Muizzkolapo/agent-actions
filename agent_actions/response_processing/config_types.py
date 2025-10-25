from typing import TypedDict, Optional, List, Dict, Any

class AgentEntryDict(TypedDict, total=False):
    """Typed representation of a single agent configuration entry."""
    agent_type: str
    name: Optional[str]
    model_name: Optional[str]
    model_vendor: Optional[str]  # Model vendor/provider: "openai", "gemini", "anthropic", "groq", or "tool"
    api_key: Optional[str]
    code_path: Optional[str]
    dependencies: List[str]
    parent: List[str]
    prompt: Optional[str]
    schema_name: Optional[str]
    chunk_config: Dict[str, Any]
    observe: List[str]
    drops: List[str]
    is_operational: bool
    few_shot: int
    conditional_clause: Optional[str]
    where_clause: Optional[Dict[str, Any]]
    skip_if: Optional[str]
    ephemeral: Optional[bool]
    add_dispatch: Optional[bool]
    # Anthropic-specific configuration options
    anthropic_version: Optional[str]  # API version header for Anthropic requests (e.g., "2023-06-01")
    enable_prompt_caching: Optional[bool]  # Enable Anthropic's prompt caching feature for improved performance

# Alias for the list of agent entries under a pipeline name
AgentConfigList = List[AgentEntryDict]

# Alias for the mapping of pipeline/agent name to its configuration list
AgentConfigMap = Dict[str, AgentConfigList]
