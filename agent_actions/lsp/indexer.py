"""Project indexer for Agent Actions LSP."""

import ast
import logging
import re
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

from .models import Location, ProjectIndex, PromptDefinition, ToolDefinition

logger = logging.getLogger(__name__)


def find_project_root(start_path: Path) -> Optional[Path]:
    """Find project root by looking for agent_actions.yml."""
    current = start_path.resolve()

    while current != current.parent:
        if (current / "agent_actions.yml").exists():
            return current
        current = current.parent

    return None


def build_index(project_root: Path) -> ProjectIndex:
    """Build complete project index."""
    index = ProjectIndex(root=project_root)

    # Index workflows
    _index_workflows(index, project_root)

    # Index prompts
    _index_prompts(index, project_root)

    # Index tools
    _index_tools(index, project_root)

    # Index schemas
    _index_schemas(index, project_root)

    logger.info(
        f"Indexed: {len(index.actions)} actions, {len(index.prompts)} prompts, "
        f"{len(index.tools)} tools, {len(index.schemas)} schemas"
    )

    return index


def _index_workflows(index: ProjectIndex, project_root: Path) -> None:
    """Index all workflow YAML files."""
    workflow_dir = project_root / "agent_workflow"
    if not workflow_dir.exists():
        return

    yaml = YAML()
    yaml.preserve_quotes = True

    for workflow_path in workflow_dir.iterdir():
        if not workflow_path.is_dir():
            continue

        index.workflows[workflow_path.name] = workflow_path

        # Find workflow config files
        config_dir = workflow_path / "agent_config"
        if not config_dir.exists():
            continue

        for yaml_file in config_dir.glob("*.yml"):
            _index_workflow_file(index, yaml_file, yaml)


def _index_workflow_file(index: ProjectIndex, yaml_file: Path, yaml: YAML) -> None:
    """Index a single workflow YAML file."""
    try:
        content = yaml_file.read_text()
        lines = content.split("\n")

        # Parse YAML
        data = yaml.load(content)
        if not data:
            return

        # Initialize file actions dict
        index.file_actions[yaml_file] = {}

        # Find actions list
        actions = data.get("actions", [])
        if not actions:
            return

        # Index each action with line numbers
        for action in actions:
            if not isinstance(action, dict):
                continue

            name = action.get("name")
            if not name:
                continue

            # Find line number by searching for "- name: {name}"
            line_num = _find_action_line(lines, name)

            location = Location(
                file_path=yaml_file,
                line=line_num,
                column=0,
            )

            index.actions[name] = location
            index.file_actions[yaml_file][name] = location

    except Exception as e:
        logger.warning(f"Error indexing {yaml_file}: {e}")


def _find_action_line(lines: list, action_name: str) -> int:
    """Find the line number where an action is defined."""
    pattern = re.compile(rf"^\s*-?\s*name:\s*['\"]?{re.escape(action_name)}['\"]?\s*$")

    for i, line in enumerate(lines):
        if pattern.match(line) or f"name: {action_name}" in line:
            return i

    return 0


def _index_prompts(index: ProjectIndex, project_root: Path) -> None:
    """Index all prompts in prompt store."""
    prompt_dir = project_root / "prompt_store"
    if not prompt_dir.exists():
        return

    prompt_pattern = re.compile(r"\{prompt\s+(\w+)\}")

    for md_file in prompt_dir.glob("*.md"):
        file_stem = md_file.stem
        content = md_file.read_text()
        lines = content.split("\n")

        for i, line in enumerate(lines):
            match = prompt_pattern.search(line)
            if match:
                prompt_name = match.group(1)
                full_name = f"{file_stem}.{prompt_name}"

                # Get preview (next 5 lines)
                preview_lines = lines[i + 1 : i + 6]
                preview = "\n".join(preview_lines)

                index.prompts[full_name] = PromptDefinition(
                    name=prompt_name,
                    full_name=full_name,
                    location=Location(file_path=md_file, line=i, column=0),
                    content_preview=preview,
                )


def _index_tools(index: ProjectIndex, project_root: Path) -> None:
    """Index all UDF tool functions."""
    tools_dir = project_root / "tools"
    if not tools_dir.exists():
        # Try qanalabs/tools structure
        tools_dir = project_root / "qanalabs" / "tools"

    if not tools_dir.exists():
        return

    for py_file in tools_dir.rglob("*.py"):
        _index_python_file(index, py_file)


def _index_python_file(index: ProjectIndex, py_file: Path) -> None:
    """Index a single Python file for UDF tools."""
    try:
        content = py_file.read_text()
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue

            # Check for @udf_tool decorator
            has_udf_decorator = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "udf_tool":
                    has_udf_decorator = True
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name) and decorator.func.id == "udf_tool":
                        has_udf_decorator = True

            if not has_udf_decorator:
                continue

            # Get function signature
            args = []
            for arg in node.args.args:
                arg_name = arg.arg
                annotation = ""
                if arg.annotation:
                    annotation = f": {ast.unparse(arg.annotation)}"
                args.append(f"{arg_name}{annotation}")

            returns = ""
            if node.returns:
                returns = f" -> {ast.unparse(node.returns)}"

            signature = f"def {node.name}({', '.join(args)}){returns}"

            # Get docstring
            docstring = ast.get_docstring(node) or ""

            index.tools[node.name] = ToolDefinition(
                name=node.name,
                location=Location(
                    file_path=py_file,
                    line=node.lineno - 1,  # AST is 1-indexed, LSP is 0-indexed
                    column=node.col_offset,
                ),
                signature=signature,
                docstring=docstring,
            )

    except Exception as e:
        logger.warning(f"Error indexing {py_file}: {e}")


def _index_schemas(index: ProjectIndex, project_root: Path) -> None:
    """Index all schema files."""
    schema_dir = project_root / "schema"
    if not schema_dir.exists():
        # Try qanalabs/schema structure
        schema_dir = project_root / "qanalabs" / "schema"

    if not schema_dir.exists():
        return

    for schema_file in schema_dir.glob("*.yml"):
        schema_name = schema_file.stem
        index.schemas[schema_name] = schema_file

    for schema_file in schema_dir.glob("*.yaml"):
        schema_name = schema_file.stem
        index.schemas[schema_name] = schema_file
