"""Data models for Agent Actions LSP."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from agent_actions.utils.constants import DEFAULT_ACTION_KIND


class ReferenceType(Enum):
    """Types of references that can be resolved."""

    PROMPT = "prompt"  # $workflow.PromptName
    TOOL = "tool"  # impl: function_name
    SCHEMA = "schema"  # schema: schema_name
    ACTION = "action"  # dependencies: [action_name]
    WORKFLOW = "workflow"  # workflow: workflow_name
    SEED_FILE = "seed_file"  # $file:path/to/file.json
    CONTEXT_FIELD = "context_field"  # context_scope.observe action.field


@dataclass
class Location:
    """A location in a file."""

    file_path: Path
    line: int  # 0-indexed
    column: int = 0
    end_line: int | None = None
    end_column: int | None = None

    def to_lsp(self) -> dict:
        """Convert to LSP Location format."""
        return {
            "uri": self.file_path.as_uri(),
            "range": {
                "start": {"line": self.line, "character": self.column},
                "end": {
                    "line": self.end_line or self.line,
                    "character": self.end_column or self.column,
                },
            },
        }


@dataclass
class Reference:
    """A reference found in a workflow file."""

    type: ReferenceType
    value: str  # The reference value (e.g., "workflow.PromptName")
    location: Location  # Where the reference appears
    raw_text: str  # The original text (e.g., "$workflow.PromptName")


@dataclass
class ActionDefinition:
    """An action defined in a workflow YAML."""

    name: str
    location: Location
    prompt_ref: str | None = None
    impl_ref: str | None = None
    schema_ref: str | None = None
    dependencies: list[str] = field(default_factory=list)
    kind: str = DEFAULT_ACTION_KIND  # "llm" or "tool"


@dataclass
class ActionMetadata:
    """Detailed action metadata captured from workflow files."""

    name: str
    location: Location
    prompt_ref: str | None = None
    impl_ref: str | None = None
    schema_ref: str | None = None
    dependencies: list[str] = field(default_factory=list)
    context_observe: list[str] = field(default_factory=list)
    context_drop: list[str] = field(default_factory=list)
    context_passthrough: list[str] = field(default_factory=list)
    guard_condition: str | None = None
    guard_line: int | None = None
    guard_variables: list[str] = field(default_factory=list)
    versions_line: int | None = None
    versions_summary: str | None = None
    versions_params: list[str] = field(default_factory=list)
    reprompt_validation: str | None = None
    reprompt_line: int | None = None


@dataclass
class PromptDefinition:
    """A prompt defined in a prompt store file."""

    name: str  # Just the prompt name
    full_name: str  # file.PromptName
    location: Location
    content_preview: str = ""  # First few lines for hover


@dataclass
class ToolDefinition:
    """A UDF tool function."""

    name: str
    location: Location
    signature: str = ""  # Function signature for hover
    docstring: str = ""  # Docstring for hover


@dataclass
class SchemaDefinition:
    """A schema definition and its fields."""

    name: str
    location: Location
    fields: list[str] = field(default_factory=list)


@dataclass
class ProjectIndex:
    """Index of all definitions in an agent-actions project."""

    root: Path

    # action_name → Location (within same workflow)
    actions: dict[str, Location] = field(default_factory=dict)

    # "file.PromptName" → PromptDefinition
    prompts: dict[str, PromptDefinition] = field(default_factory=dict)

    # function_name → ToolDefinition
    tools: dict[str, ToolDefinition] = field(default_factory=dict)

    # schema_name → definition
    schemas: dict[str, SchemaDefinition] = field(default_factory=dict)

    # workflow_name → directory_path
    workflows: dict[str, Path] = field(default_factory=dict)

    # Per-file action index: file_path → {action_name → ActionMetadata}
    # NOTE: This replaces the previous Location-only entries for richer metadata.
    file_actions: dict[Path, dict[str, ActionMetadata]] = field(default_factory=dict)

    # Per-workflow action index: workflow_name → {action_name → Location}
    workflow_actions: dict[str, dict[str, Location]] = field(default_factory=dict)

    # Cached workflow derivation: file_path → workflow_name (populated at index time)
    file_to_workflow: dict[Path, str] = field(default_factory=dict)

    # Per-file reference list: file_path → [Reference]
    references_by_file: dict[Path, list[Reference]] = field(default_factory=dict)

    # Per-file duplicate action names: file_path → {duplicate action name}
    duplicate_actions_by_file: dict[Path, set[str]] = field(default_factory=dict)

    # Upstream action index: workflow_name → {action_name → Location}
    # Actions declared in upstream: blocks, resolvable only within the declaring workflow.
    upstream_actions: dict[str, dict[str, Location]] = field(default_factory=dict)

    def workflow_for_file(self, file_path: Path) -> str | None:
        """Derive the workflow name from a file path.

        Looks for 'agent_workflow/{name}/...' in the path components.
        Returns None for flat-layout files.
        """
        parts = file_path.parts
        for i, part in enumerate(parts):
            if part == "agent_workflow" and i + 1 < len(parts):
                return parts[i + 1]
        return None

    def get_action(self, name: str, current_file: Path | None = None) -> Location | None:
        """Get action location: per-file → per-workflow → upstream → global (flat layout only)."""
        # 1. Same file (most specific)
        if current_file and current_file in self.file_actions:
            if name in self.file_actions[current_file]:
                return self.file_actions[current_file][name].location

        # 2. Same workflow — if file belongs to a workflow, check local then upstream
        if current_file:
            workflow = self.workflow_for_file(current_file)
            if workflow:
                if workflow in self.workflow_actions:
                    local = self.workflow_actions[workflow].get(name)
                    if local:
                        return local
                # 3. Upstream actions declared by this workflow
                if workflow in self.upstream_actions:
                    upstream = self.upstream_actions[workflow].get(name)
                    if upstream:
                        return upstream
                return None

        # 4. Global fallback (flat layout or no current_file)
        return self.actions.get(name)

    def get_action_metadata(
        self, name: str, current_file: Path | None = None
    ) -> ActionMetadata | None:
        """Get action metadata: per-file → same-workflow files → upstream → any file (flat layout only)."""
        # 1. Same file
        if current_file and current_file in self.file_actions:
            if name in self.file_actions[current_file]:
                return self.file_actions[current_file][name]

        # 2. Same workflow — if file belongs to a workflow, search only that workflow's files
        if current_file:
            workflow = self.file_to_workflow.get(current_file) or self.workflow_for_file(
                current_file
            )
            if workflow:
                for file_path, actions in self.file_actions.items():
                    if self.file_to_workflow.get(file_path) == workflow and name in actions:
                        return actions[name]
                # 3. Upstream — return minimal metadata (no schema/hover info)
                if workflow in self.upstream_actions and name in self.upstream_actions[workflow]:
                    return ActionMetadata(name=name, location=self.upstream_actions[workflow][name])
                return None

        # 4. Any file (flat layout or no current_file)
        for actions in self.file_actions.values():
            if name in actions:
                return actions[name]
        return None

    def get_prompt(self, ref: str) -> PromptDefinition | None:
        """Get prompt by reference (file.PromptName)."""
        return self.prompts.get(ref)

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get tool by function name."""
        return self.tools.get(name)

    def get_schema(self, name: str) -> Path | None:
        """Get schema file path by name (legacy helper)."""
        return self.get_schema_path(name)

    def get_schema_path(self, name: str) -> Path | None:
        """Get schema file path by name."""
        schema = self.schemas.get(name)
        if schema:
            return schema.location.file_path
        return None

    def get_schema_definition(self, name: str) -> SchemaDefinition | None:
        """Get schema definition by name."""
        return self.schemas.get(name)

    def get_workflow(self, name: str) -> Path | None:
        """Get workflow directory by name."""
        return self.workflows.get(name)
