"""Project indexer for Agent Actions LSP."""

import ast
import logging
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from agent_actions.config.path_config import get_tool_dirs, load_project_config
from agent_actions.config.schema import version_variant_names
from agent_actions.errors import ConfigValidationError
from agent_actions.prompt.handler import PROMPT_PATTERN as _PROMPT_PATTERN
from agent_actions.utils.file_utils import load_structured_file, read_python_source
from agent_actions.utils.path_utils import resolve_relative_to
from agent_actions.utils.project_root import find_project_root as _find_project_root_canonical

from .models import (
    ActionMetadata,
    Location,
    ProjectIndex,
    PromptDefinition,
    Reference,
    ReferenceType,
    SchemaDefinition,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


def find_project_root(start_path: Path) -> Path | None:
    """Find project root by looking for agent_actions.yml.

    Searches upward first (via canonical util), then searches subdirectories
    if not found.
    """
    # Delegate upward walk to canonical implementation
    result = _find_project_root_canonical(str(start_path))
    if result is not None:
        return result

    # LSP-specific: glob downward up to 3 levels
    start = start_path.resolve() if start_path.is_dir() else start_path.parent
    for depth in range(1, 4):
        pattern = "/".join(["*"] * depth) + "/agent_actions.yml"
        matches = list(start.glob(pattern))
        if matches:
            return matches[0].parent

    return None


def find_all_project_roots(workspace_folders: list[Path]) -> list[Path]:
    """Discover all agent_actions.yml project roots across workspace folders."""
    roots: set[Path] = set()
    for folder in workspace_folders:
        folder = folder.resolve()
        # Delegate upward walk to canonical implementation
        upward_root = _find_project_root_canonical(str(folder))
        if upward_root is not None:
            roots.add(upward_root)
        # LSP-specific: glob downward up to 3 levels
        start = folder if folder.is_dir() else folder.parent
        for depth in range(1, 4):
            pattern = "/".join(["*"] * depth) + "/agent_actions.yml"
            for match in start.glob(pattern):
                roots.add(match.parent.resolve())
    return sorted(roots)


def build_index(project_root: Path) -> ProjectIndex:
    """Build complete project index."""
    index = ProjectIndex(root=project_root)

    _index_workflows(index, project_root)
    _index_prompts(index, project_root)
    tool_paths = get_tool_dirs(project_root)
    _index_tools(index, project_root, tool_paths)
    _index_schemas(index, project_root)

    logger.info(
        f"Indexed: {len(index.actions)} actions, {len(index.prompts)} prompts, "
        f"{len(index.tools)} tools, {len(index.schemas)} schemas"
    )

    return index


def _project_output_field(project_root: Path) -> str | None:
    """`output_field` set once in the project config, which reaches every action.

    Through load_project_config because the project file has four accepted spellings
    (agent_actions.yml/.yaml, .agent_actions.yml, config/agent_actions.yml); reading only
    the first means every bare guard name is reported in a project using any of the others.
    """
    try:
        data = load_project_config(project_root)
    except Exception as e:
        logger.debug("project config not readable yet: %s", e)
        return None
    defaults = data.get("default_agent_config") if isinstance(data, dict) else None
    value = defaults.get("output_field") if isinstance(defaults, dict) else None
    return value if isinstance(value, str) else None


def _index_workflows(index: ProjectIndex, project_root: Path) -> None:
    """Index all workflow YAML files."""
    workflow_dir = project_root / "agent_workflow"
    if not workflow_dir.exists():
        return

    yaml = YAML(typ="safe")
    project_output_field = _project_output_field(project_root)

    for workflow_path in workflow_dir.iterdir():
        if not workflow_path.is_dir():
            continue

        index.workflows[workflow_path.name] = workflow_path

        config_dir = workflow_path / "agent_config"
        if not config_dir.exists():
            continue

        for yaml_file in config_dir.glob("*.yml"):
            _index_workflow_file(index, yaml_file, yaml, project_output_field)


def _index_workflow_file(
    index: ProjectIndex, yaml_file: Path, yaml: YAML, project_output_field: str | None = None
) -> None:
    """Index a single workflow YAML file."""
    try:
        content = yaml_file.read_text()
        lines = content.split("\n")

        data = yaml.load(content) or {}
        index.file_actions[yaml_file] = {}
        index.references_by_file[yaml_file] = []
        index.duplicate_actions_by_file[yaml_file] = set()

        actions = data.get("actions", []) if isinstance(data, dict) else []
        action_data_map = _build_action_data_map(actions)
        defaults = data.get("defaults") if isinstance(data, dict) else None
        workflow_default = defaults.get("output_field") if isinstance(defaults, dict) else None
        default_output_field = workflow_default or project_output_field

        _index_workflow_lines(index, yaml_file, lines, action_data_map, default_output_field)
        _backfill_unseen_actions(index, yaml_file, lines, action_data_map, default_output_field)

    except Exception as e:
        logger.warning("Error indexing %s: %s", yaml_file, e)


def _backfill_unseen_actions(
    index: ProjectIndex,
    yaml_file: Path,
    lines: list[str],
    action_data_map: dict,
    default_output_field: str | None,
) -> None:
    """Index an action the line pass could not see, so the index matches the document.

    The line pass recognises an action by `- name:` opening the list item. YAML does not
    care about key order, and the loader does not either, so `- kind: tool` then `name: x`
    is a valid action that never reached the index -- which turned every reference to it
    into an Unresolved error and, worse, switched the bare-name check off for everything
    downstream of it.
    """
    known = index.file_actions.setdefault(yaml_file, {})
    for action_name, action_data in action_data_map.items():
        if action_name in known:
            continue
        line_no, column = 0, 0
        for i, line in enumerate(lines):
            match = re.match(rf"^\s*-?\s*name:\s*['\"]?{re.escape(action_name)}['\"]?\s*$", line)
            if match:
                line_no, column = i, line.index(action_name)
                break
        meta = ActionMetadata(
            name=action_name,
            location=Location(
                file_path=yaml_file,
                line=line_no,
                column=column,
                end_line=line_no,
                end_column=column + len(action_name),
            ),
        )
        _populate_versions_summary(meta, action_data)
        _populate_from_parsed(meta, action_data, default_output_field)
        known[action_name] = meta
        index.actions[action_name] = meta.location
        workflow_name = index.file_to_workflow.get(yaml_file)
        if workflow_name:
            index.workflow_actions.setdefault(workflow_name, {})[action_name] = meta.location


def _build_action_data_map(actions: list) -> dict:
    """Build a map of action name to parsed action data."""
    action_map = {}
    for action in actions:
        if isinstance(action, dict) and action.get("name"):
            action_map[action["name"]] = action
    return action_map


def _index_workflow_lines(
    index: ProjectIndex,
    yaml_file: Path,
    lines: list[str],
    action_data_map: dict,
    default_output_field: str | None = None,
) -> None:
    """Index action metadata and references from workflow lines.

    `default_output_field` comes from the parsed `defaults:` block rather than from these
    lines, because a `defaults:` written after `actions:` is legal and a line scan reaches
    it only before the first action.
    """
    workflow_name = index.workflow_for_file(yaml_file)
    if workflow_name:
        index.file_to_workflow[yaml_file] = workflow_name

    current_action = None
    current_action_indent = None
    dependencies_indent = None
    context_scope_indent = None
    context_list_indent = None
    current_context_list = None

    for i, line in enumerate(lines):
        action_match = re.match(r"^(\s*)-\s*name:\s*['\"]?([^'\"#]+?)['\"]?\s*(?:#.*)?$", line)
        if action_match:
            action_name = action_match.group(2)
            action_indent = len(action_match.group(1))
            action_location = Location(
                file_path=yaml_file,
                line=i,
                column=action_match.start(2),
                end_line=i,
                end_column=action_match.start(2) + len(action_name),
            )
            if action_name in index.file_actions[yaml_file]:
                index.duplicate_actions_by_file[yaml_file].add(action_name)
            action_meta = ActionMetadata(name=action_name, location=action_location)
            index.file_actions[yaml_file][action_name] = action_meta
            index.actions[action_name] = action_location
            if workflow_name:
                index.workflow_actions.setdefault(workflow_name, {})[action_name] = action_location

            action_data = action_data_map.get(action_name, {})
            _populate_versions_summary(action_meta, action_data)
            _populate_from_parsed(action_meta, action_data, default_output_field)

            current_action = action_meta
            current_action_indent = action_indent
            dependencies_indent = None
            context_scope_indent = None
            context_list_indent = None
            current_context_list = None
            continue

        if not current_action:
            continue

        line_indent = len(line) - len(line.lstrip())
        if (
            line.strip()
            and current_action_indent is not None
            and line_indent <= current_action_indent
        ):
            current_action = None
            current_action_indent = None
            dependencies_indent = None
            context_scope_indent = None
            context_list_indent = None
            current_context_list = None
            continue

        # Prompt reference
        prompt_match = re.search(r"prompt:\s*\$(\w+)\.(\w+)", line)
        if prompt_match:
            full_ref = f"{prompt_match.group(1)}.{prompt_match.group(2)}"
            current_action.prompt_ref = full_ref
            _add_reference(
                index,
                yaml_file,
                ReferenceType.PROMPT,
                full_ref,
                i,
                prompt_match.start(1) - 1,
                prompt_match.end(2),
                prompt_match.group(0),
            )

        # Tool reference
        impl_match = re.search(r"impl:\s*(\w+)", line)
        if impl_match:
            current_action.impl_ref = impl_match.group(1)
            _add_reference(
                index,
                yaml_file,
                ReferenceType.TOOL,
                impl_match.group(1),
                i,
                impl_match.start(1),
                impl_match.end(1),
                impl_match.group(0),
            )

        # Schema reference
        schema_match = re.search(r"schema:\s*(\w+)", line)
        if schema_match:
            current_action.schema_ref = schema_match.group(1)
            _add_reference(
                index,
                yaml_file,
                ReferenceType.SCHEMA,
                schema_match.group(1),
                i,
                schema_match.start(1),
                schema_match.end(1),
                schema_match.group(0),
            )

        # Dependencies block
        if re.match(r"^\s*dependencies:\s*$", line):
            dependencies_indent = line_indent
            continue

        if dependencies_indent is not None:
            if line.strip() and line_indent <= dependencies_indent:
                dependencies_indent = None
            else:
                dep_match = re.match(r"^\s*-\s*([^\s#]+)", line)
                if dep_match:
                    dep_name, _ = _unquoted(dep_match.group(1).strip().strip(","))
                    _add_reference(
                        index,
                        yaml_file,
                        ReferenceType.ACTION,
                        dep_name,
                        i,
                        dep_match.start(1),
                        dep_match.start(1) + len(dep_name),
                        dep_name,
                    )

        deps_list_match = re.search(r"dependencies:\s*\[([^\]]+)\]", line)
        if deps_list_match:
            list_content = deps_list_match.group(1)
            list_start = deps_list_match.start(1)
            for action_match in re.finditer(r"(\w+)", list_content):
                dep_name = action_match.group(1)
                _add_reference(
                    index,
                    yaml_file,
                    ReferenceType.ACTION,
                    dep_name,
                    i,
                    list_start + action_match.start(1),
                    list_start + action_match.end(1),
                    dep_name,
                )

        if re.match(r"^\s*context_scope:\s*$", line):
            context_scope_indent = line_indent
            context_list_indent = None
            current_context_list = None
            continue

        if context_scope_indent is not None:
            if line.strip() and line_indent <= context_scope_indent:
                context_scope_indent = None
                context_list_indent = None
                current_context_list = None
            else:
                observe_match = re.match(r"^\s*observe:\s*$", line)
                drop_match = re.match(r"^\s*drop:\s*$", line)
                passthrough_match = re.match(r"^\s*passthrough:\s*$", line)
                if observe_match:
                    current_context_list = "observe"
                    context_list_indent = line_indent
                elif drop_match:
                    current_context_list = "drop"
                    context_list_indent = line_indent
                elif passthrough_match:
                    current_context_list = "passthrough"
                    context_list_indent = line_indent
                elif current_context_list and context_list_indent is not None:
                    item_match = re.match(r"^\s*-\s*([^\s#]+)", line)
                    if not item_match and line.strip() and line_indent <= context_list_indent:
                        # A non-list-item at or before list indent means we've exited the list
                        current_context_list = None
                    elif item_match:
                        # Only the reference range is taken here. The quotes are YAML's:
                        # left on, `- 'up.title'` resolves as the action `'up` and is
                        # reported unresolvable at Error severity.
                        value, offset = _unquoted(item_match.group(1).strip())
                        _add_reference(
                            index,
                            yaml_file,
                            ReferenceType.CONTEXT_FIELD,
                            value,
                            i,
                            item_match.start(1) + offset,
                            item_match.start(1) + offset + len(value),
                            value,
                        )

        # Only the anchor line is taken here -- both spellings, inline and block, and either
        # may carry a trailing comment. The condition itself comes from the parsed document.
        if re.match(r"^\s*guard:\s*(#.*|\{.*|\S.*)?$", line):
            current_action.guard_line = i
            continue

        # Same two spellings, and the inline one is what real configs write: the sample
        # project's six versioned actions all use it, so matching only the block form left
        # versions_line unset on every one of them and the CodeLens never appeared.
        if re.match(r"^\s*versions:\s*(#.*|\{.*)?$", line):
            current_action.versions_line = i
            continue

        # Seed file references
        file_match = re.search(r"\$file:([^\s,\}]+)", line)
        if file_match:
            _add_reference(
                index,
                yaml_file,
                ReferenceType.SEED_FILE,
                file_match.group(1),
                i,
                file_match.start(1) - 6,
                file_match.end(1),
                file_match.group(0),
            )


def _add_reference(
    index: ProjectIndex,
    yaml_file: Path,
    ref_type: ReferenceType,
    value: str,
    line: int,
    start: int,
    end: int,
    raw_text: str,
) -> None:
    """Add a reference to the index."""
    index.references_by_file[yaml_file].append(
        Reference(
            type=ref_type,
            value=value,
            location=Location(
                file_path=yaml_file,
                line=line,
                column=start,
                end_line=line,
                end_column=end,
            ),
            raw_text=raw_text,
        )
    )


# Match length is preserved by the substitution below so any downstream
# offset-based mapping over the sanitised string stays valid.
_QUOTED_LITERAL_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*'"
)


def _blank_out_quoted_literals(condition: str) -> str:
    return _QUOTED_LITERAL_RE.sub(lambda m: " " * (m.end() - m.start()), condition)


def _condition_keywords() -> frozenset[str]:
    """Words the guard language owns, so none is mistaken for a field reference.

    From the operator registry, not copied: a hand-written list drifts the moment an
    operator is added, and the symptom is a warning on a correct clause. The cost is a field
    genuinely named `length` -- WhereClauseParser accepts these bare, so it is never checked.
    The alternative warns on `a.b CONTAINS "x"`, which the docs teach.
    """
    from agent_actions.input.preprocessing.parsing.operators import FUNCTIONS, OPERATOR_INFO

    words = {"and", "or", "not", "in", "is", "true", "false", "null", "none"}
    words.update(name.lower() for name in FUNCTIONS)
    for info in OPERATOR_INFO.values():
        symbol = getattr(info, "symbol", "")
        for word in str(symbol).split():
            if word.isalpha():
                words.add(word.lower())
    return frozenset(words)


_CONDITION_KEYWORDS = _condition_keywords()


def _extract_condition_variables(condition: str) -> list[str]:
    """Extract variable-like tokens from a guard/validation condition.

    Identifiers inside single- or double-quoted string literals are
    ignored — they are values, not variable references.
    """
    if condition.strip().startswith("udf:"):
        # A UDF guard names a python callable, not fields. The framework's own checker
        # skips it the same way (workflow_static_analyzer); without this the module path
        # and the `udf` prefix are both reported as missing namespaces.
        return []
    sanitised = _blank_out_quoted_literals(condition)
    return [
        m.group(0)
        for m in re.finditer(r"\b[a-zA-Z_][\w\.]*\b", sanitised)
        if m.group(0).lower() not in _CONDITION_KEYWORDS
        and not sanitised[m.end() :].lstrip().startswith("(")
    ]


def _populate_versions_summary(action_meta: ActionMetadata, action_data: dict) -> None:
    """Populate versions summary info from parsed YAML data."""
    versions = action_data.get("versions")
    if not versions:
        return
    summaries = []
    params = []

    if isinstance(versions, dict):
        versions = [versions]

    if isinstance(versions, list):
        for version in versions:
            if not isinstance(version, dict):
                continue
            param = version.get("param")
            if param:
                params.append(param)
            range_value = version.get("range")
            parts = []
            if param:
                parts.append(f"param `{param}`")
            if range_value:
                parts.append(f"range `{range_value}`")
            if parts:
                summaries.append(", ".join(parts))

    action_meta.versions_params = params
    if summaries:
        action_meta.versions_summary = "; ".join(summaries)


def _unquoted(raw: str) -> tuple[str, int]:
    """Strip YAML's surrounding quotes, returning the value and how far the start moved."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1], 1
    return raw, 0


def _populate_from_parsed(
    action_meta: ActionMetadata, action_data: dict, default_output_field: str | None
) -> None:
    """Set the fields the guard check reads from the PARSED document.

    Scanning lines for these values means re-implementing YAML: five separate defects came
    from it -- outer quotes left on, a trailing `# comment` swallowed as part of the value,
    a quoted `output_field`, quoted list items, and `>-` block scalars. The loader has
    already resolved all of that, so take the values from it and leave the line scan to do
    what only it can: positions and reference ranges.
    """
    output_field = action_data.get("output_field", default_output_field)
    if isinstance(output_field, str):
        action_meta.output_field = output_field

    guard = action_data.get("guard")
    # `guard:` is `str | dict` in ActionConfig; six framework sites branch on the string
    # form, so reading only the mapping leaves those actions unchecked.
    condition = (
        guard
        if isinstance(guard, str)
        else guard.get("condition")
        if isinstance(guard, dict)
        else None
    )
    if isinstance(condition, str) and condition.strip():
        action_meta.guard_condition = condition
        action_meta.guard_variables = _extract_condition_variables(condition)

    deps = action_data.get("dependencies")
    if isinstance(deps, str):
        deps = [deps]
    if isinstance(deps, list):
        # Line-scanned, `- 'up'` kept its quotes and became the action `'up`, which
        # get_action_metadata cannot find -- and an unknown upstream switches the whole
        # bare-name check off. Same defect as the context_scope items, same cause.
        action_meta.dependencies.extend(str(d) for d in deps if isinstance(d, str | int | float))

    scope = action_data.get("context_scope")
    if isinstance(scope, dict):
        for directive, target in (
            ("observe", action_meta.context_observe),
            ("passthrough", action_meta.context_passthrough),
            ("drop", action_meta.context_drop),
        ):
            refs = scope.get(directive)
            if isinstance(refs, str):
                refs = [refs]
            if isinstance(refs, list):
                target.extend(str(ref) for ref in refs if isinstance(ref, str | int | float))

    # The one shape that inverts namespacing. Same three conditions the framework's own
    # validate_version_merge_output_namespaces uses, so the two cannot drift.
    granularity = str(action_data.get("granularity") or "").lower()
    is_tool = action_data.get("kind") == "tool" or action_data.get("model_vendor") == "tool"
    action_meta.spreads_output_flat = bool(
        granularity == "file" and is_tool and action_data.get("version_consumption")
    )

    versions = action_data.get("versions")
    if versions:
        try:
            action_meta.version_variants = version_variant_names(action_meta.name, versions)
        except Exception as e:
            # A workflow under the cursor is half-written most of the time; an unparseable
            # versions block is the author's next keystroke, not an indexer error.
            logger.debug("versions block for %s not expandable yet: %s", action_meta.name, e)


def _index_prompts(index: ProjectIndex, project_root: Path) -> None:
    """Index all prompts using PromptLoader's discovery logic."""
    from agent_actions.prompt.handler import PromptLoader

    for md_file in PromptLoader.discover_prompt_files(project_root):
        file_stem = md_file.stem
        try:
            content = md_file.read_text()
        except (OSError, UnicodeDecodeError):
            logger.warning("LSP indexer: skipping unreadable prompt file %s", md_file)
            continue
        lines = content.split("\n")

        for i, line in enumerate(lines):
            match = _PROMPT_PATTERN.search(line)
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


def _index_tools(index: ProjectIndex, project_root: Path, tool_paths: list[str]) -> None:
    """Index all UDF tool functions using the shared discovery filter."""
    from agent_actions.input.loaders.udf import discover_tool_files

    for rel_path in tool_paths:
        tools_dir = resolve_relative_to(rel_path, project_root)
        for py_file in discover_tool_files(tools_dir):
            _index_python_file(index, py_file)


def _index_python_file(index: ProjectIndex, py_file: Path) -> None:
    """Index a single Python file for UDF tools."""
    try:
        content = read_python_source(py_file)
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue

            has_udf_decorator = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "udf_tool":
                    has_udf_decorator = True
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name) and decorator.func.id == "udf_tool":
                        has_udf_decorator = True

            if not has_udf_decorator:
                continue

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
        logger.warning("Error indexing %s: %s", py_file, e)


def _index_schemas(index: ProjectIndex, project_root: Path) -> None:
    """Index all schema files using SchemaLoader's discovery logic.

    Reuses ``SchemaLoader.discover_schema_files()`` so that directory
    traversal, recursive search, and uniqueness rules stay in one place.
    The LSP adds its own metadata (Location, extracted fields) on top.
    """
    from agent_actions.output.response.loader import SchemaLoader

    try:
        all_schemas = SchemaLoader.discover_schema_files(project_root)
    except (ConfigValidationError, OSError) as e:
        logger.warning("LSP indexer: could not discover schemas: %s", e)
        return

    for schema_name, schema_file in all_schemas.items():
        fields = _extract_schema_fields(schema_file)
        index.schemas[schema_name] = SchemaDefinition(
            name=schema_name,
            location=Location(file_path=schema_file, line=0, column=0),
            fields=fields,
        )


def _extract_schema_fields(schema_file: Path) -> list[str]:
    """Extract schema fields for diagnostics and completions."""
    try:
        data = load_structured_file(schema_file)
    except Exception as e:
        logger.debug("Could not extract schema fields from %s: %s", schema_file, e)
        return []

    if not isinstance(data, dict):
        return []

    fields: list[str] = []
    _collect_schema_fields(data, fields)
    return fields


def _collect_schema_fields(data: Any, fields: list[str], prefix: str = "") -> None:
    """Collect schema fields from properties or field lists."""
    if not isinstance(data, dict):
        return

    properties = data.get("properties")
    if isinstance(properties, dict):
        for key, value in properties.items():
            name = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            fields.append(name)
            if isinstance(value, dict):
                _collect_schema_fields(value, fields, name)

    field_list = data.get("fields")
    if isinstance(field_list, list):
        for item in field_list:
            if isinstance(item, dict) and ("name" in item or "id" in item):
                field_name = item.get("name") or item.get("id")
                name = f"{prefix}{field_name}" if not prefix else f"{prefix}.{field_name}"
                fields.append(name)
