"""Data models for Agent Actions LSP."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


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
    end_line: Optional[int] = None
    end_column: Optional[int] = None

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
    prompt_ref: Optional[str] = None
    impl_ref: Optional[str] = None
    schema_ref: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    kind: str = "llm"  # "llm" or "tool"


@dataclass
class ActionMetadata:
    """Detailed action metadata captured from workflow files."""

    name: str
    location: Location
    prompt_ref: Optional[str] = None
    impl_ref: Optional[str] = None
    schema_ref: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    context_observe: List[str] = field(default_factory=list)
    context_drop: List[str] = field(default_factory=list)
    guard_condition: Optional[str] = None
    guard_line: Optional[int] = None
    guard_variables: List[str] = field(default_factory=list)
    versions_line: Optional[int] = None
    versions_summary: Optional[str] = None
    versions_params: List[str] = field(default_factory=list)
    reprompt_validation: Optional[str] = None
    reprompt_line: Optional[int] = None


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
    fields: List[str] = field(default_factory=list)


@dataclass
class ProjectIndex:
    """Index of all definitions in an agent-actions project."""

    root: Path

    # action_name → Location (within same workflow)
    actions: Dict[str, Location] = field(default_factory=dict)

    # "file.PromptName" → PromptDefinition
    prompts: Dict[str, PromptDefinition] = field(default_factory=dict)

    # function_name → ToolDefinition
    tools: Dict[str, ToolDefinition] = field(default_factory=dict)

    # schema_name → definition
    schemas: Dict[str, SchemaDefinition] = field(default_factory=dict)

    # workflow_name → directory_path
    workflows: Dict[str, Path] = field(default_factory=dict)

    # Per-file action index: file_path → {action_name → ActionMetadata}
    file_actions: Dict[Path, Dict[str, ActionMetadata]] = field(default_factory=dict)

    # Per-file reference list: file_path → [Reference]
    references_by_file: Dict[Path, List[Reference]] = field(default_factory=dict)

    # Per-file duplicate action names: file_path → [duplicate action name]
    duplicate_actions_by_file: Dict[Path, List[str]] = field(default_factory=dict)

    def get_action(self, name: str, current_file: Optional[Path] = None) -> Optional[Location]:
        """Get action location, preferring same-file actions."""
        # First check same file
        if current_file and current_file in self.file_actions:
            if name in self.file_actions[current_file]:
                return self.file_actions[current_file][name].location

        # Fall back to global
        return self.actions.get(name)

    def get_action_metadata(
        self, name: str, current_file: Optional[Path] = None
    ) -> Optional[ActionMetadata]:
        """Get action metadata, preferring same-file actions."""
        if current_file and current_file in self.file_actions:
            if name in self.file_actions[current_file]:
                return self.file_actions[current_file][name]
        if current_file:
            for actions in self.file_actions.values():
                if name in actions:
                    return actions[name]
        return None

    def get_prompt(self, ref: str) -> Optional[PromptDefinition]:
        """Get prompt by reference (file.PromptName)."""
        return self.prompts.get(ref)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool by function name."""
        return self.tools.get(name)

    def get_schema(self, name: str) -> Optional[Path]:
        """Get schema file path by name."""
        schema = self.schemas.get(name)
        if schema:
            return schema.location.file_path
        return None

    def get_schema_definition(self, name: str) -> Optional[SchemaDefinition]:
        """Get schema definition by name."""
        return self.schemas.get(name)

    def get_workflow(self, name: str) -> Optional[Path]:
        """Get workflow directory by name."""
        return self.workflows.get(name)
