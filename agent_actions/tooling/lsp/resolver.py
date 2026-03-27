"""Reference resolver for Agent Actions LSP."""

import re
from pathlib import Path

from .models import Location, ProjectIndex, Reference, ReferenceType
from .utils import is_in_context_scope_list, is_in_dependencies_context


def get_reference_at_position(content: str, line: int, character: int) -> Reference | None:
    """Detect what reference (if any) is at the given position."""
    lines = content.split("\n")
    if line >= len(lines):
        return None

    current_line = lines[line]

    # Check various reference patterns

    # 1. Prompt reference: prompt: $workflow.PromptName
    prompt_match = re.search(r"prompt:\s*\$(\w+)\.(\w+)", current_line)
    if prompt_match:
        start = prompt_match.start(1) - 1  # Include the $
        end = prompt_match.end(2)
        if start <= character <= end:
            full_ref = f"{prompt_match.group(1)}.{prompt_match.group(2)}"
            return Reference(
                type=ReferenceType.PROMPT,
                value=full_ref,
                location=Location(file_path=Path(), line=line, column=start),
                raw_text=prompt_match.group(0),
            )

    # 2. Tool implementation: impl: function_name
    impl_match = re.search(r"impl:\s*(\w+)", current_line)
    if impl_match:
        start = impl_match.start(1)
        end = impl_match.end(1)
        if start <= character <= end:
            return Reference(
                type=ReferenceType.TOOL,
                value=impl_match.group(1),
                location=Location(file_path=Path(), line=line, column=start),
                raw_text=impl_match.group(0),
            )

    # 3. Schema reference: schema: schema_name
    schema_match = re.search(r"schema:\s*(\w+)", current_line)
    if schema_match:
        start = schema_match.start(1)
        end = schema_match.end(1)
        if start <= character <= end:
            return Reference(
                type=ReferenceType.SCHEMA,
                value=schema_match.group(1),
                location=Location(file_path=Path(), line=line, column=start),
                raw_text=schema_match.group(0),
            )

    # 4. Dependency reference (simple): - action_name
    dep_match = re.search(r"^\s*-\s*(\w+)\s*$", current_line)
    if dep_match and is_in_dependencies_context(lines, line):
        start = dep_match.start(1)
        end = dep_match.end(1)
        if start <= character <= end:
            return Reference(
                type=ReferenceType.ACTION,
                value=dep_match.group(1),
                location=Location(file_path=Path(), line=line, column=start),
                raw_text=dep_match.group(1),
            )

    # 5. Dependency reference (in list): dependencies: [action1, action2]
    deps_list_match = re.search(r"dependencies:\s*\[([^\]]+)\]", current_line)
    if deps_list_match:
        list_content = deps_list_match.group(1)
        list_start = deps_list_match.start(1)

        # Find which action the cursor is on
        actions = re.finditer(r"(\w+)", list_content)
        for action_match in actions:
            abs_start = list_start + action_match.start(1)
            abs_end = list_start + action_match.end(1)
            if abs_start <= character <= abs_end:
                return Reference(
                    type=ReferenceType.ACTION,
                    value=action_match.group(1),
                    location=Location(file_path=Path(), line=line, column=abs_start),
                    raw_text=action_match.group(1),
                )

    # 6. Workflow reference: workflow: workflow_name
    workflow_match = re.search(r"workflow:\s*(\w+)", current_line)
    if workflow_match:
        start = workflow_match.start(1)
        end = workflow_match.end(1)
        if start <= character <= end:
            return Reference(
                type=ReferenceType.WORKFLOW,
                value=workflow_match.group(1),
                location=Location(file_path=Path(), line=line, column=start),
                raw_text=workflow_match.group(0),
            )

    # 7. Seed file reference: $file:path/to/file.json
    file_match = re.search(r"\$file:([^\s,\}]+)", current_line)
    if file_match:
        start = file_match.start(1)
        end = file_match.end(1)
        if start - 6 <= character <= end:  # -6 for "$file:"
            return Reference(
                type=ReferenceType.SEED_FILE,
                value=file_match.group(1),
                location=Location(file_path=Path(), line=line, column=start - 6),
                raw_text=file_match.group(0),
            )

    # 8. Context scope references: - action.field
    context_match = re.search(r"^\s*-\s*([A-Za-z_][\w\.]*)", current_line)
    if context_match and is_in_context_scope_list(lines, line):
        start = context_match.start(1)
        end = context_match.end(1)
        if start <= character <= end:
            return Reference(
                type=ReferenceType.CONTEXT_FIELD,
                value=context_match.group(1),
                location=Location(file_path=Path(), line=line, column=start),
                raw_text=context_match.group(1),
            )

    return None


def resolve_reference(
    reference: Reference, index: ProjectIndex, current_file: Path | None = None
) -> Location | None:
    """Resolve a reference to its target location."""
    if reference.type == ReferenceType.PROMPT:
        prompt = index.get_prompt(reference.value)
        if prompt:
            return prompt.location

    elif reference.type == ReferenceType.TOOL:
        tool = index.get_tool(reference.value)
        if tool:
            return tool.location

    elif reference.type == ReferenceType.SCHEMA:
        schema_path = index.get_schema_path(reference.value)
        if schema_path:
            return Location(file_path=schema_path, line=0, column=0)

    elif reference.type == ReferenceType.ACTION:
        return index.get_action(reference.value, current_file)

    elif reference.type == ReferenceType.WORKFLOW:
        workflow_path = index.get_workflow(reference.value)
        if workflow_path:
            # Return the first YAML file in the config directory
            config_dir = workflow_path / "agent_config"
            if config_dir.exists():
                for yaml_file in config_dir.glob("*.yml"):
                    return Location(file_path=yaml_file, line=0, column=0)
            return Location(file_path=workflow_path, line=0, column=0)

    elif reference.type == ReferenceType.SEED_FILE:
        # Resolve relative to seed_data directory
        seed_path = index.root / "seed_data" / reference.value
        if seed_path.exists():
            return Location(file_path=seed_path, line=0, column=0)

        # Also check workflow-specific seed_data (only when inside agent_config/ tree)
        if current_file:
            ancestor = current_file.parent
            while ancestor != ancestor.parent:
                if ancestor.name == "agent_config":
                    workflow_seed = ancestor.parent / "seed_data" / reference.value
                    if workflow_seed.exists():
                        return Location(file_path=workflow_seed, line=0, column=0)
                    break
                ancestor = ancestor.parent

    elif reference.type == ReferenceType.CONTEXT_FIELD:
        action_name = reference.value.split(".", 1)[0]
        return index.get_action(action_name, current_file)

    return None
