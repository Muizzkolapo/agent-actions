"""Configuration schema models for agent response processing."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from agent_actions.config.schema import ChunkConfig
from agent_actions.config.types import RunMode
from agent_actions.llm.config.vendor import canonical_vendor, vendor_names


class DefaultAgentConfig(BaseModel):
    """Default settings applied to each agent configuration (post-expansion stage).

    Used in ``ConfigManager.merge_agent_configs()`` to validate project-level
    defaults *after* ``ActionExpander`` has transformed actions into agents.
    For pre-expansion defaults validation, see ``DefaultsConfig`` in
    ``agent_actions.config.schema``.
    """

    api_key: SecretStr | None = None
    model_name: str | None = None
    chunk_config: ChunkConfig | None = None
    is_operational: bool = True
    run_mode: RunMode = RunMode.ONLINE
    # Declared on both models: `default_agent_config:` reaches an agent only through
    # these, which allow extras and would otherwise take any value.
    request_timeout: float | None = Field(
        default=None, strict=True, gt=0, allow_inf_nan=False, description="Default request timeout"
    )
    record_concurrency: int | None = Field(
        default=None, strict=True, ge=1, le=32, description="Default record concurrency"
    )
    vendor_params: dict[str, Any] | None = Field(
        default=None, description="Default request parameters passed to the vendor SDK"
    )
    model_config = ConfigDict(extra="allow")


class AgentConfig(BaseModel):
    """Schema for an individual agent configuration entry (post-expansion stage).

    Validates the agent dict *after* ``ActionExpander`` has transformed
    pre-expansion ``ActionConfig`` dicts into the runtime agent shape
    (adding ``agent_type``, ``code_path``, ``schema_name``, etc.).

    Uses ``extra="allow"`` because the expander injects many fields
    not declared here.  For pre-expansion action validation, see
    ``ActionConfig`` in ``agent_actions.config.schema``.
    """

    agent_type: str
    name: str | None = None
    model_name: str | None = None
    model_vendor: str | None = Field(
        default=None,
        description="Model vendor/provider: " + ", ".join(f"'{v}'" for v in vendor_names()),
    )
    api_key: SecretStr | None = None
    code_path: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    prompt: str | None = None
    schema_name: str | None = None
    chunk_config: ChunkConfig = Field(default_factory=ChunkConfig)
    is_operational: bool = True
    add_dispatch: bool | None = None
    run_mode: RunMode = RunMode.ONLINE
    json_mode: bool = Field(default=True, description="Enable JSON mode for structured output")
    prompt_debug: bool = Field(
        default=False, description="Enable debug output showing prompts being sent to the agent"
    )
    anthropic_version: str | None = Field(
        default=None, description="API version header for Anthropic requests (e.g., '2023-06-01')"
    )
    enable_prompt_caching: bool | None = Field(
        default=None,
        description="Enable Anthropic's prompt caching feature for improved performance",
    )
    conditional_clause: str | None = Field(
        default=None, description="UDF guard condition, written by the expander"
    )
    request_timeout: float | None = Field(
        default=None,
        strict=True,
        gt=0,
        allow_inf_nan=False,
        description="Seconds one LLM request may take before it fails as a retriable error",
    )
    record_concurrency: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=32,
        description="Records of an online LLM action in flight at once",
    )
    vendor_params: dict[str, Any] | None = Field(
        default=None, description="Request parameters passed to the vendor SDK as written"
    )
    on_empty: Literal["warn", "error", "skip"] = Field(
        default="warn", description="What an empty answer does to its record or action"
    )
    context_scope: dict[str, Any] | None = Field(
        default=None,
        description="Context scope configuration for data visibility and flow control "
        "(seed, observe, drop directives). Normalized in-place by config pipeline "
        "(version references expanded to field prefix patterns).",
    )

    @field_validator("model_vendor", mode="before")
    @classmethod
    def _one_name_for_a_vendor(cls, value: Any) -> Any:
        return canonical_vendor(value)

    model_config = ConfigDict(extra="allow")


__all__ = [
    "DefaultAgentConfig",
    "AgentConfig",
]
