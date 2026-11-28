"""Project indexer for Agent Actions LSP."""

import ast
import logging
import re
from collections.abc import Container
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from agent_actions.config.includes import branch_file
from agent_actions.config.loops import is_loop
from agent_actions.config.path_config import (
    get_tool_dirs,
    load_project_config,
    project_config_file,
)
from agent_actions.config.schema import version_variant_names
from agent_actions.errors import ConfigValidationError
from agent_actions.input.context.normalizer import observe_entry_reference
from agent_actions.output.response.dispatch_injection import schema_dispatch_function
from agent_actions.output.response.expander_validation import routing_kind
from agent_actions.prompt.handler import PROMPT_PATTERN as _PROMPT_PATTERN
from agent_actions.utils.file_utils import load_structured_file, read_python_source
from agent_actions.utils.path_utils import resolve_relative_to
from agent_actions.utils.project_root import find_project_root as _find_project_root_canonical

from .jinja_source import WorkflowRenderError, render_workflow_source
from .models import (
    ActionMetadata,
    Location,
    ParseError,
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

    _index_connections(index, project_root)
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


def _index_connections(index: ProjectIndex, project_root: Path) -> None:
    """Where the project file's `connections:` block names each connection."""
    try:
        declared = load_project_config(project_root).get("connections")
    except Exception as e:
        logger.debug("project config not readable yet: %s", e)
        return
    names = (
        [name for name, settings in declared.items() if isinstance(settings, dict)]
        if isinstance(declared, dict)
        else []
    )
    config_file = project_config_file(project_root)
    lines = config_file.read_text(encoding="utf-8").split("\n") if config_file else []
    index.connections = {
        str(name): _connection_location(config_file or project_root, lines, str(name))
        for name in names
    }


def _connection_location(config_file: Path, lines: list[str], name: str) -> Location:
    """The line of the `connections:` block that names *name*; the block's own if none does."""
    line_no, column = 0, 0
    in_block = False
    for i, line in enumerate(lines):
        if re.match(r"^\S", line) and not line.startswith("#"):
            if in_block:
                break
            in_block = re.match(r"^connections:\s*(?:#.*)?$", line) is not None
            if in_block:
                line_no = i
            continue
        match = re.match(rf"^\s+['\"]?({re.escape(name)})['\"]?\s*:", line) if in_block else None
        if match:
            line_no, column = i, match.start(1)
            break
    return Location(
        file_path=config_file,
        line=line_no,
        column=column,
        end_line=line_no,
        end_column=column + len(name),
    )


def _index_workflows(index: ProjectIndex, project_root: Path) -> None:
    """Index all workflow YAML files."""
    workflow_dir = project_root / "agent_workflow"
    if not workflow_dir.exists():
        return

    project_output_field = _project_output_field(project_root)

    for workflow_path in workflow_dir.iterdir():
        if not workflow_path.is_dir():
            continue

        index.workflows[workflow_path.name] = workflow_path

        config_dir = workflow_path / "agent_config"
        if not config_dir.exists():
            continue

        for yaml_file in config_dir.glob("*.yml"):
            _index_workflow_file(index, yaml_file, project_output_field)


def _index_workflow_file(
    index: ProjectIndex, yaml_file: Path, project_output_field: str | None = None
) -> None:
    """Index a single workflow file, from the text `agac` renders it to."""
    index.file_actions[yaml_file] = {}
    index.references_by_file[yaml_file] = []
    index.duplicate_actions_by_file[yaml_file] = set()
    workflow_name = index.workflow_for_file(yaml_file)
    if workflow_name:
        index.file_to_workflow[yaml_file] = workflow_name
    try:
        lines = yaml_file.read_text().split("\n")
        try:
            rendered = render_workflow_source(yaml_file, index.root)
        except WorkflowRenderError as e:
            index.parse_errors[yaml_file] = ParseError(e.message, Location(yaml_file, e.line))
            return

        data = rendered.data
        actions = data.get("actions", [])
        action_data_map = _build_action_data_map(actions)
        defaults = data.get("defaults")
        workflow_default = defaults.get("output_field") if isinstance(defaults, dict) else None
        default_output_field = workflow_default or project_output_field

        _index_workflow_lines(
            index,
            yaml_file,
            lines,
            action_data_map,
            default_output_field,
            action_lines=rendered.action_lines,
            live_lines=rendered.live_lines,
            line_owners=rendered.line_owners,
            line_paths=rendered.line_paths,
        )
        _backfill_unseen_actions(
            index,
            yaml_file,
            lines,
            action_data_map,
            default_output_field,
            rendered.action_sources,
            rendered.live_lines,
        )
        _index_database_references(index, yaml_file, lines, rendered.line_paths)
        _drop_jinja_line_references(index, yaml_file, lines)
        index.duplicate_actions_by_file[yaml_file].update(_repeated_names(actions))
        _index_included_outputs(index, yaml_file, actions, default_output_field)
        _index_entry_actions(index, yaml_file, lines, actions, rendered.live_lines)

    except Exception as e:
        logger.warning("Error indexing %s: %s", yaml_file, e)


_TAGS_ONLY = re.compile(r"\s*(?:(?:\{%.*?%\}|\{#.*?#\})\s*)+")
_MAY_OUTPUT = re.compile(r"\{\{|\{%[-+]?\s*(?:include|call)\b")


def _defines_action(
    line_no: int, name: str, action_lines: frozenset[int] | None, action_data_map: dict
) -> bool:
    return name in action_data_map and (action_lines is None or line_no in action_lines)


def _drop_jinja_line_references(index: ProjectIndex, yaml_file: Path, lines: list[str]) -> None:
    """A line that holds a Jinja tag names what the render makes of it, not its literal words."""
    index.references_by_file[yaml_file] = [
        ref
        for ref in index.references_by_file[yaml_file]
        if not any(opener in lines[ref.location.line] for opener in ("{{", "{%", "{#"))
    ]


def _repeated_names(actions: Any) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for action in actions if isinstance(actions, list) else []:
        name = action.get("name") if isinstance(action, dict) else None
        if isinstance(name, str):
            (repeated if name in seen else seen).add(name)
    return repeated


def _backfill_unseen_actions(
    index: ProjectIndex,
    yaml_file: Path,
    lines: list[str],
    action_data_map: dict,
    default_output_field: str | None,
    action_sources: dict[str, Location],
    live_lines: frozenset[int] | None = None,
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
        location = action_sources.get(action_name) or _name_location(
            yaml_file, lines, action_name, live_lines=live_lines
        )
        meta = ActionMetadata(name=action_name, location=location)
        _populate_versions_summary(meta, action_data)
        _populate_from_parsed(meta, action_data, default_output_field)
        known[action_name] = meta
        index.actions[action_name] = meta.location
        workflow_name = index.file_to_workflow.get(yaml_file)
        if workflow_name:
            index.workflow_actions.setdefault(workflow_name, {})[action_name] = meta.location


def _name_location(
    file_path: Path,
    lines: list[str],
    action_name: str,
    key: str = "name",
    live_lines: frozenset[int] | None = None,
) -> Location:
    """Where `<key>: <action_name>` is written in *lines*; the file's start if nowhere."""
    line_no, column = 0, 0
    for i, line in enumerate(lines):
        # In a mapped Jinja file only marked lines are written as-is; an empty set means the
        # map was not trusted, so the first written line is the best guess.
        if live_lines and (key == "name" or i not in live_lines):
            continue
        match = re.match(
            rf"^\s*-?\s*{key}:\s*['\"]?({re.escape(action_name)})['\"]?\s*(?:#.*)?$", line
        )
        if match:
            line_no, column = i, match.start(1)
            break
    return Location(
        file_path=file_path,
        line=line_no,
        column=column,
        end_line=line_no,
        end_column=column + len(action_name),
    )


def _index_included_outputs(
    index: ProjectIndex,
    yaml_file: Path,
    actions: list,
    default_output_field: str | None,
) -> None:
    """Index the outputs of each branch the workflow includes as actions of the workflow.

    The load puts a branch's actions into the workflow under their own names, or under
    `<as>__<name>` for an include with `as:`, and the workflow may read only the ones the
    branch lists under `outputs`.
    """
    known = index.file_actions.setdefault(yaml_file, {})
    workflow_name = index.file_to_workflow.get(yaml_file)
    for entry in actions:
        if not isinstance(entry, dict) or not isinstance(entry.get("include"), str):
            continue
        # Outside a loop only its name is read; `_index_entry_actions` indexes it.
        if is_loop(entry):
            continue
        branch_path = index.root / branch_file(entry["include"])
        try:
            content = branch_path.read_text()
            branch = YAML(typ="safe").load(content)
        except (OSError, YAMLError) as e:
            logger.warning("Error indexing branch file %s: %s", branch_path, e)
            continue
        outputs = branch.get("outputs") if isinstance(branch, dict) else None
        branch_actions = branch.get("actions") if isinstance(branch, dict) else None
        if not isinstance(outputs, list) or not isinstance(branch_actions, list):
            continue
        lines = content.split("\n")
        prefix = entry.get("as") if isinstance(entry.get("as"), str) else None
        for action_data in branch_actions:
            local = action_data.get("name") if isinstance(action_data, dict) else None
            if not isinstance(local, str) or local not in outputs:
                continue
            name = f"{prefix}__{local}" if prefix else local
            if name in known:
                continue
            meta = ActionMetadata(name=name, location=_name_location(branch_path, lines, local))
            _populate_versions_summary(meta, action_data)
            _populate_from_parsed(meta, action_data, default_output_field)
            known[name] = meta
            index.actions[name] = meta.location
            if workflow_name:
                index.workflow_actions.setdefault(workflow_name, {})[name] = meta.location


_ENTRY_KEYS = ("route", "join", "loop")


_DATABASE_KEY = re.compile(
    r"^(\s*(?:-\s+)?)(action|connection):"  # the key
    r"\s*(['\"]?)([\w.-]+)\3\s*(?:#.*)?$"  # its name, quoted or not
)


def _index_database_references(
    index: ProjectIndex,
    yaml_file: Path,
    lines: list[str],
    line_paths: dict[int, tuple[str, ...] | None] | None,
) -> None:
    """Index the action each `outputs:` entry writes, and each connection a workflow names.

    A line counts only where the render puts it under the key it writes, so an `action:`
    in a prompt or a dropped Jinja branch is not read.
    """
    if line_paths is None:
        return
    for i, line in enumerate(lines):
        match = _DATABASE_KEY.match(line)
        path = line_paths.get(i)
        if not match or not path or path[-1] != match.group(2):
            continue
        key, value = match.group(2), match.group(4)
        if key == "action" and path != ("outputs", "-", "action"):
            continue
        if key == "connection" and path[:2] != ("outputs", "-") and "data_source" not in path:
            continue
        start = match.end(3)
        _add_reference(
            index,
            yaml_file,
            ReferenceType.ACTION if key == "action" else ReferenceType.CONNECTION,
            value,
            i,
            start,
            start + len(value),
            value,
        )


def _index_entry_actions(
    index: ProjectIndex,
    yaml_file: Path,
    lines: list[str],
    actions: list,
    live_lines: frozenset[int] | None = None,
) -> None:
    """Index the action each `- route:`, `- join:` and `- loop:` entry becomes, by its name.

    The load writes the router, the join and the loop's result action under the entry's
    name, so the workflow reads that name as an action's.
    """
    known = index.file_actions.setdefault(yaml_file, {})
    workflow_name = index.file_to_workflow.get(yaml_file)
    for entry in actions:
        if not isinstance(entry, dict) or "name" in entry:
            continue
        key = next((k for k in _ENTRY_KEYS if isinstance(entry.get(k), str)), None)
        if key is None or entry[key] in known:
            continue
        name = entry[key]
        meta = ActionMetadata(
            name=name,
            location=_name_location(yaml_file, lines, name, key, live_lines=live_lines),
        )
        meta.dependencies.extend(_entry_reads(key, entry))
        known[name] = meta
        index.actions[name] = meta.location
        if workflow_name:
            index.workflow_actions.setdefault(workflow_name, {})[name] = meta.location
    _index_retrieve_steps(index, yaml_file, lines, actions)


def _index_retrieve_steps(
    index: ProjectIndex, yaml_file: Path, lines: list[str], actions: list
) -> None:
    """Index the step each `context_scope.retrieve` entry becomes: `<action>__<entry>`.

    Another action reads the matches by that name; the step's fields are fixed.
    """
    known = index.file_actions.setdefault(yaml_file, {})
    workflow_name = index.file_to_workflow.get(yaml_file)
    for action in actions:
        scope = action.get("context_scope") if isinstance(action, dict) else None
        entries = scope.get("retrieve") if isinstance(scope, dict) else None
        if not isinstance(entries, dict) or not isinstance(action.get("name"), str):
            continue
        owner = known.get(action["name"])
        start = owner.location.line if owner is not None else 0
        if owner is not None:
            owner.retrieve_entries = [e for e in entries if isinstance(e, str)]
        for entry in entries:
            name = f"{action['name']}__{entry}"
            if not isinstance(entry, str) or name in known:
                continue
            line_no = next(
                (
                    i
                    for i in range(start, len(lines))
                    if re.match(rf"^\s*{re.escape(entry)}:\s*(?:#.*)?$", lines[i])
                ),
                start,
            )
            column = len(lines[line_no]) - len(lines[line_no].lstrip()) if lines else 0
            location = Location(
                file_path=yaml_file,
                line=line_no,
                column=column,
                end_line=line_no,
                end_column=column + len(entry),
            )
            meta = ActionMetadata(name=name, location=location)
            meta.dependencies.extend(_retrieve_reads(entries[entry], known))
            known[name] = meta
            index.actions[name] = location
            if workflow_name:
                index.workflow_actions.setdefault(workflow_name, {})[name] = location


def _retrieve_reads(entry: Any, actions: Container[str] = ()) -> list[str]:
    """The actions the `query` and `where` refs of a retrieve entry read, and the action its
    `from:` names when it names one of *actions* rather than a knowledge base."""
    if not isinstance(entry, dict):
        return []
    searched = entry.get("from")
    corpus = [searched] if isinstance(searched, str) and searched in actions else []
    query = entry.get("query")
    refs = [query] if isinstance(query, str) else list(query) if isinstance(query, list) else []
    where = entry.get("where")
    refs += [v for v in where.values() if isinstance(v, str)] if isinstance(where, dict) else []
    roots = [ref.split(".", 1)[0] for ref in refs if isinstance(ref, str) and "." in ref]
    return list(dict.fromkeys([*(root for root in roots if root != "source"), *corpus]))


def _entry_reads(key: str, entry: dict) -> list[str]:
    """The workflow actions a route, join or loop entry reads."""
    if key == "route":
        # YAML 1.1 reads a bare `on` key as the boolean true.
        on = entry.get("on", entry.get(True))
        return [on.split(".", 1)[0]] if isinstance(on, str) else []
    if key == "join":
        of = entry.get("of")
        return [str(name) for name in of if isinstance(name, str)] if isinstance(of, list) else []
    inputs = entry.get("inputs")
    return (
        [str(v) for v in inputs.values() if isinstance(v, str)] if isinstance(inputs, dict) else []
    )


def _build_action_data_map(actions: list) -> dict:
    """Build a map of action name to parsed action data."""
    action_map = {}
    for action in actions:
        # PyYAML reads `name: yes` as True, which names no action.
        if isinstance(action, dict) and isinstance(action.get("name"), str) and action["name"]:
            action_map[action["name"]] = action
    return action_map


def _index_workflow_lines(  # noqa: C901
    index: ProjectIndex,
    yaml_file: Path,
    lines: list[str],
    action_data_map: dict,
    default_output_field: str | None = None,
    action_lines: frozenset[int] | None = None,
    live_lines: frozenset[int] | None = None,
    line_owners: dict[int, str | None] | None = None,
    line_paths: dict[int, tuple[str, ...] | None] | None = None,
) -> None:
    """Index action metadata and references from workflow lines.

    `default_output_field` comes from the parsed `defaults:`, which may follow `actions:`.
    The lines are the file as written: `live_lines` skips what the render drops,
    `action_lines` says which `- name:` lines define an action, and `line_owners` says
    which action the render puts each line in. A reference is taken only where
    `line_paths` puts its line under the key its type reads.
    """

    def under(line_no: int, *keys: str | None) -> bool:
        if line_paths is None or line_no not in line_paths:
            return True
        path = line_paths[line_no]
        return path is not None and all(key in path for key in keys)

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
        if action_match and not _defines_action(
            i, action_match.group(2), action_lines, action_data_map
        ):
            # Not an action of the render: a name a tag renders, a line in a dropped branch,
            # or a `- name:` inside a prompt or schema. A sibling of the current action ends it.
            if (
                current_action_indent is None
                or len(action_match.group(1)) <= current_action_indent
            ):
                current_action = None
                current_action_indent = None
            continue
        if (live_lines is not None and i not in live_lines) or _TAGS_ONLY.fullmatch(line):
            # A dropped line, or a line of `{% %}` / `{# #}` tags. A line that can output
            # text can open a key, so it closes each nested block it is not inside; the
            # action itself ends where `line_owners` says.
            if _MAY_OUTPUT.search(line):
                indent = len(line) - len(line.lstrip())
                if dependencies_indent is not None and indent <= dependencies_indent:
                    dependencies_indent = None
                if context_scope_indent is not None and indent <= context_scope_indent:
                    context_scope_indent = None
                    context_list_indent = None
                    current_context_list = None
                if context_list_indent is not None and indent <= context_list_indent:
                    context_list_indent = None
                    current_context_list = None
            continue
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
        if (
            line_owners is not None
            and line_owners.get(i, current_action.name) != current_action.name
        ):
            # A tag above this line output another action, and this line is its text. A
            # line with no mark (a `filter` body) is output where it is written.
            continue

        # A tag on the line renders to words the line does not show.
        holds_tag = any(opener in line for opener in ("{{", "{%", "{#"))

        # Prompt reference
        prompt_match = re.search(r"prompt:\s*\$(\w+)\.(\w+)", line)
        if prompt_match and not holds_tag and under(i, "prompt"):
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
        if impl_match and re.match(r"agac\.(route|pick)\b", line[impl_match.start(1) :]):
            impl_match = None
        if impl_match and not holds_tag and under(i, "impl"):
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
        if (
            schema_match
            and not holds_tag
            and under(i, "schema")
            and not _dispatches_schema(line[schema_match.start(1) :])
        ):
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
                if dep_match and under(i, "dependencies"):
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
        if deps_list_match and under(i, "dependencies"):
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
                    elif under(i, "context_scope", current_context_list):
                        # Only the reference range is taken here. The quotes are YAML's:
                        # left on, `- 'up.title'` resolves as the action `'up` and is
                        # reported unresolvable at Error severity.
                        found = _context_item_reference(
                            line, item_match, optional_forms=current_context_list == "observe"
                        )
                        if found:
                            value, start = found
                            _add_reference(
                                index,
                                yaml_file,
                                ReferenceType.CONTEXT_FIELD,
                                value,
                                i,
                                start,
                                start + len(value),
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


def _dispatches_schema(value: str) -> bool:
    """Whether a ``schema:`` line's value is a dispatch call, which names no schema file."""
    return schema_dispatch_function(value.split(" #", 1)[0].strip()) is not None


# The `field:` key of an observe entry written as a mapping, block or flow.
_MAPPING_FIELD = re.compile(r"(?:^\s*(?:-\s*)?|[{,]\s*)field:\s*([^\s#,}]+)")


def _context_item_reference(
    line: str, item_match: re.Match[str] | None, *, optional_forms: bool
) -> tuple[str, int] | None:
    """The reference a context_scope list line names, and the column it starts at.

    An observe entry may be optional: `- a.b?`, or a mapping whose `field:` names it.
    """
    mapping = optional_forms and (
        item_match is None or item_match.group(1).endswith(":") or item_match.group(1)[0] == "{"
    )
    if item_match and not mapping:
        raw, start = item_match.group(1).strip(), item_match.start(1)
    elif mapping and (field := _MAPPING_FIELD.search(line)):
        raw, start = field.group(1), field.start(1)
    else:
        return None
    value, offset = _unquoted(raw)
    if optional_forms:
        value = value.removesuffix("?")
    return value, start + offset


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
                if directive == "observe":
                    refs = [observe_entry_reference(ref) or ref for ref in refs]
                target.extend(str(ref) for ref in refs if isinstance(ref, str | int | float))

    # The one shape that inverts namespacing. Same three conditions the framework's own
    # validate_version_merge_output_namespaces uses, so the two cannot drift.
    granularity = str(action_data.get("granularity") or "").lower()
    is_tool = routing_kind(action_data) == "tool"
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
