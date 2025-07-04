from typing import TypedDict, Optional, List, Dict, Any

class AgentEntryDict(TypedDict, total=False):
    """Typed representation of a single agent configuration entry."""
    agent_type: str
    name: Optional[str]
    model_name: Optional[str]
    model_vendor: Optional[str]
    api_key: Optional[str]
    code_path: Optional[str]
    dependencies: List[str]
    parent: List[str]
    prompt: Optional[str]
    schema_name: Optional[str]
    chunk_config: Dict[str, Any]
    side_collection: List[str]
    is_operational: bool
    use_few_shot_samples: int
    conditional_clause: Optional[str]
    ephemeral: Optional[bool]
    add_dispatch: Optional[bool]

# Alias for the list of agent entries under a pipeline name
AgentConfigList = List[AgentEntryDict]

# Alias for the mapping of pipeline/agent name to its configuration list
AgentConfigMap = Dict[str, AgentConfigList]
