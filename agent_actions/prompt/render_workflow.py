"""Render and compile workflow templates into self-contained YAML."""

import functools
import logging
import textwrap
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import jinja2
import yaml
from jinja2 import Environment, StrictUndefined

from agent_actions.config.path_config import resolve_project_root
from agent_actions.config.schema import validate_version_block
from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.output.response.loader import SchemaLoader
from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder
from agent_actions.prompt.deferred_tags import (
    DeferringFileSystemLoader,
    defer_unresolved_tags,
    is_marked,
    render_marked,
    strip_marks,
    template_folder_exports,
)
from agent_actions.prompt.handler import PromptLoader
from agent_actions.utils.safe_format import safe_format_error
from agent_actions.utils.schema_utils import is_compiled_schema

logger = logging.getLogger(__name__)


def _load_template_globals(env, templates_folder):
    """
    Load and register all Jinja2 templates and their globals.

    Args:
        env: Jinja2 Environment instance
        templates_folder: Path to templates directory
    """
    templates_path = Path(templates_folder)
    # A project with no templates/ is as valid as one with an empty templates/;
    # exists() rather than is_dir() so a non-directory at that path still raises.
    if not templates_path.exists():
        logger.debug(
            "No templates directory at %s, so there are no globals to load.", templates_path
        )
        return
    template_files = [p.name for p in templates_path.iterdir() if p.suffix in (".j2", ".jinja2")]
    for template_file in template_files:
        try:
            template = env.get_template(template_file)
            module = template.module
            new_names = vars(module)
            collisions = set(new_names) & set(env.globals)
            if collisions:
                logger.warning(
                    "Template '%s' redefines global name(s) already set by a previous template: %s. "
                    "The previous definition(s) will be overwritten.",
                    template_file,
                    ", ".join(sorted(collisions)),
                )
            env.globals.update(new_names)
        except jinja2.TemplateNotFound:
            logger.warning("Template file '%s' not found in %s.", template_file, templates_folder)
        except jinja2.TemplateSyntaxError as e:
            raise TemplateRenderingError(
                "Syntax error in template",
                context={
                    "template_file": template_file,
                    "line": e.lineno,
                    "message": e.message,
                    "templates_folder": templates_folder,
                },
                cause=e,
            ) from e
        except Exception as e:
            raise TemplateRenderingError(
                f"Unexpected error loading template '{template_file}': {safe_format_error(e)}",
                context={"template_file": template_file, "templates_folder": templates_folder},
                cause=e,
            ) from e


def _save_failed_render(rendered_yaml_content, workflow_name, project_root: Path | None = None):
    """
    Save failed render output to cache for debugging.

    Args:
        rendered_yaml_content: The rendered YAML that failed to parse
        workflow_name: Name of the workflow for the cache filename
        project_root: Optional project root directory

    Returns:
        Error message string with path to saved file

    Raises:
        OSError: If the file cannot be written (disk full, permissions, etc.)
    """
    cache_dir = (
        resolve_project_root(project_root) / ".agent-actions" / "cache" / "rendered_workflows"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    failed_render_path = cache_dir / f"{workflow_name}_failed.yml"
    with open(failed_render_path, "w", encoding="utf-8") as f:
        f.write(rendered_yaml_content)
    return f"\nRendered output saved to: {failed_render_path}"


def _resolve_prompt_fields(item, project_root: Path | None = None):
    """
    Recursively resolve prompt fields starting with '$'.

    Searches for keys named 'prompt' whose values begin with '$'
    and resolves them using PromptLoader.load_prompt.

    Args:
        item: Dictionary, list, or other value to process
        project_root: Optional project root for prompt file search
    """
    if isinstance(item, dict):
        for key, value in item.items():
            if key == "prompt" and isinstance(value, str):
                if value.strip().startswith("$"):
                    parts = value.strip().split(maxsplit=1)
                    prompt_key = parts[0][1:]
                    extra = parts[1] if len(parts) > 1 else ""
                    try:
                        resolved = PromptLoader.load_prompt(prompt_key, project_root=project_root)
                        item[key] = resolved + (" " + extra if extra else "")
                    except ValueError as e:
                        raise ConfigurationError(
                            f"Failed to resolve prompt reference '{value}'",
                            context={
                                "prompt_reference": value,
                                "prompt_key": prompt_key,
                                "operation": "resolve_prompt_field",
                            },
                            cause=e,
                        ) from e
            elif isinstance(value, dict | list):
                _resolve_prompt_fields(value, project_root=project_root)
    elif isinstance(item, list):
        for sub_item in item:
            _resolve_prompt_fields(sub_item, project_root=project_root)


# =============================================================================
# Schema Compilation Functions
# =============================================================================


def _expand_inline_schema(schema_dict: dict[str, str]) -> dict[str, Any]:
    """
    Expand inline schema dict format to unified schema format.

    Converts shorthand: {"field_name": "string", "count": "number!"}
    To unified format: {"name": "InlineSchema", "fields": [...]}

    Args:
        schema_dict: Simple dict with field_name: type mappings

    Returns:
        Unified schema format
    """
    fields = []
    for field_name, field_type in schema_dict.items():
        # Handle required marker
        is_required = field_type.endswith("!")
        if is_required:
            field_type = field_type[:-1]

        # Handle array types
        if field_type.startswith("array[") and field_type.endswith("]"):
            item_type = field_type[6:-1]
            field_def = {
                "id": field_name,
                "type": "array",
                "items": {"type": item_type},
                "required": is_required,
            }
        elif field_type == "array":
            field_def = {
                "id": field_name,
                "type": "array",
                "items": {"type": "string"},
                "required": is_required,
            }
        else:
            field_def = {
                "id": field_name,
                "type": field_type,
                "required": is_required,
            }

        fields.append(field_def)

    return {"name": "InlineSchema", "fields": fields}


def _is_inline_schema_dict(schema_value: Any) -> bool:
    """
    Check if a schema value is an inline schema dict (shorthand format).

    Inline schema dicts have string keys and string values representing types.
    Example: {"field_name": "string", "count": "number"}

    Already unified format if it has 'fields' key with a list value.
    """
    if not isinstance(schema_value, dict):
        return False

    # Already unified format - has 'fields' key with list of field definitions
    if "fields" in schema_value and isinstance(schema_value.get("fields"), list):
        return False

    # Empty dict is not an inline schema
    if not schema_value:
        return False

    # Check if all values are type strings (inline schema format)
    valid_types = {"string", "number", "integer", "boolean", "array", "object"}
    for value in schema_value.values():
        if not isinstance(value, str):
            return False
        # Strip required marker for type check
        check_type = value.rstrip("!")
        # Handle array[type] format
        if check_type.startswith("array[") and check_type.endswith("]"):
            check_type = "array"
        if check_type not in valid_types:
            return False

    return True


def _compile_action_schemas(
    action: dict[str, Any],
    schema_dir: Path | None = None,
    strict: bool = False,
    errors: list[str] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """
    Compile schemas for a single action, inlining named schemas and expanding inline ones.

    This is the core compilation step that ensures actions have self-contained schemas.
    Handles three input formats:
    1. schema_name: "foo" -> loads schema/foo.yml
    2. schema: "foo" (string) -> loads schema/foo.yml
    3. schema: {field: type} (inline dict) -> expands to unified format

    Args:
        action: Action configuration dict
        schema_dir: Optional schema directory
        strict: If True, collect errors instead of logging warnings
        errors: List to collect error messages (used with strict mode)
        project_root: Optional project root for deriving schema_dir

    Returns:
        Action with compiled schema (modified in place and returned)
    """
    action_name = action.get("name", "unknown")

    # Handle schema_name: "foo" -> load and inline
    schema_name = action.get("schema_name")
    if schema_name and isinstance(schema_name, str):
        try:
            loaded_schema = SchemaLoader.load_schema(schema_name, project_root=project_root)
            action["schema"] = loaded_schema
            del action["schema_name"]
            logger.debug("Inlined named schema '%s' for action '%s'", schema_name, action_name)
        except FileNotFoundError as e:
            error_msg = f"Action '{action_name}': Could not load schema '{schema_name}' - {e}"
            if strict and errors is not None:
                errors.append(error_msg)
            else:
                logger.warning("Could not load schema '%s' for inlining", schema_name)

    # Handle schema: "foo" (string reference) -> load and inline
    schema_value = action.get("schema")
    if schema_value and isinstance(schema_value, str):
        try:
            loaded_schema = SchemaLoader.load_schema(schema_value, project_root=project_root)
            action["schema"] = loaded_schema
            logger.debug("Inlined schema reference '%s' for action '%s'", schema_value, action_name)
        except FileNotFoundError as e:
            error_msg = f"Action '{action_name}': Could not load schema '{schema_value}' - {e}"
            if strict and errors is not None:
                errors.append(error_msg)
            else:
                logger.warning("Could not load schema '%s' for inlining", schema_value)

    # Handle schema: {field: type} (inline dict) -> expand to unified format
    schema_value = action.get("schema")
    if schema_value and _is_inline_schema_dict(schema_value):
        action["schema"] = _expand_inline_schema(schema_value)
        logger.debug("Expanded inline schema for action '%s'", action_name)
    elif schema_value and isinstance(schema_value, dict) and not is_compiled_schema(schema_value):
        logger.warning(
            "Action '%s' has an inline schema that is not in shorthand or compiled "
            "format — it may contain nested dict values. Consider using a schema file.",
            action_name,
        )

    return action


def _compile_workflow_schemas(
    data: dict[str, Any],
    schema_dir: Path | None = None,
    strict: bool = False,
    project_root: Path | None = None,
) -> None:
    """
    Compile all schemas in a workflow configuration.

    Args:
        data: Workflow configuration dict (modified in place)
        schema_dir: Optional schema directory
        strict: If True, raise ConfigurationError on any schema load failure
        project_root: Optional project root for deriving schema_dir

    Raises:
        ConfigurationError: If strict=True and any schema fails to load
    """
    errors: list[str] = []

    # Compile schemas in actions list
    actions = data.get("actions", [])
    for action in actions:
        _compile_action_schemas(
            action, schema_dir, strict=strict, errors=errors, project_root=project_root
        )

    # Raise aggregated errors in strict mode (after all schemas processed)
    if strict and errors:
        raise ConfigurationError(
            f"Schema compilation failed with {len(errors)} error(s)",
            context={
                "errors": errors,
                "operation": "compile_workflow_schemas",
                "hint": "Ensure all referenced schema files exist in the schema/ directory",
            },
        )


# =============================================================================
# Version Expansion Functions
# =============================================================================


def _apply_version_template(
    value: Any, param_name: str, current_val: int | str, idx: int, values: list[int | str]
) -> Any:
    """
    Apply version template substitution to a value.

    Replaces ${param} with current value and ${param-1} with previous value.

    Args:
        value: Value to process (string, dict, list, or other)
        param_name: Name of the version parameter (e.g., "i")
        current_val: Current iteration value
        idx: Current index in the iteration
        values: List of all iteration values

    Returns:
        Value with templates replaced
    """
    if isinstance(value, str):
        result = value.replace(f"${{{param_name}}}", str(current_val))
        if idx > 0:
            prev_value = values[idx - 1]
            result = result.replace(f"${{{param_name}-1}}", str(prev_value))
        else:
            result = result.replace(f"${{{param_name}-1}}", "")
        return result
    elif isinstance(value, dict):
        return {
            _apply_version_template(k, param_name, current_val, idx, values)
            if isinstance(k, str)
            else k: _apply_version_template(v, param_name, current_val, idx, values)
            for k, v in value.items()
        }
    elif isinstance(value, list):
        return [
            _apply_version_template(item, param_name, current_val, idx, values) for item in value
        ]
    return value


# Renders the marked tags of a value with the names a stage supplies; see deferred_tags.
MarkedRenderer = Callable[[str, Mapping[str, Any], str], str]


def _render_marked_values(
    value: Any, render: MarkedRenderer, context: Mapping[str, Any], where: str
) -> Any:
    """*value* with every marked string in it rendered with *context*, keys included."""
    if isinstance(value, str):
        return render(value, context, where) if is_marked(value) else value
    if isinstance(value, dict):
        return {
            _render_marked_values(k, render, context, where): _render_marked_values(
                v, render, context, f"{where}.{k}" if where else str(k)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _render_marked_values(item, render, context, f"{where}[{i}]")
            for i, item in enumerate(value)
        ]
    return value


def _left_tags_note(undefined: set[str], per_record: set[str]) -> str:
    """Why tags of the file were left in place, for a YAML error they may have caused."""
    reasons = []
    if undefined:
        reasons.append(f"{_quoted(undefined)}, which nothing in it defines")
    if per_record:
        reasons.append(f"{_quoted(per_record)}, which a prompt sets or tests per record")
    if not reasons:
        return ""
    return (
        f" (the file names {'; and '.join(reasons)}; those tags were left in place, as only "
        "an action's prompt renders per record)"
    )


def _quoted(names: set[str]) -> str:
    return ", ".join(repr(name) for name in sorted(names))


def _strip_prompt_marks(data: Any) -> None:
    """An action's prompt keeps the tags the load left: the per-record render reads them."""
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        return
    for action in data["actions"]:
        if isinstance(action, dict) and isinstance(action.get("prompt"), str):
            action["prompt"] = strip_marks(action["prompt"])


def _expand_versioned_action(
    action: dict[str, Any], render: MarkedRenderer | None = None
) -> list[dict[str, Any]]:
    """
    Expand a versioned action into multiple actions.

    Takes an action with versions config and expands it into N actions,
    one for each version in the range.

    Args:
        action: Action with versions configuration

    Returns:
        List of expanded action dictionaries

    Example:
        Input action with versions: {param: i, range: [1, 3]}
        Output: 3 actions with names action_1, action_2, action_3
    """
    validated = validate_version_block(action.get("versions", {}), action.get("name", "unknown"))
    param_name = validated.param
    version_range = validated.range

    # Calculate range values
    range_values: list[int | str]
    if len(version_range) == 2:
        # A pair is a start and an end; the block's validator has already refused a
        # pair that is not integers, so counting between them cannot fail here.
        start, end = int(version_range[0]), int(version_range[1])
        range_values = list(range(start, end + 1))
    else:
        range_values = list(version_range)

    total_versions = len(range_values)
    expanded_actions = []

    base_name = action.get("name", "unknown")

    for idx, i in enumerate(range_values):
        # Create a copy of the action without the versions key
        expanded = {k: v for k, v in action.items() if k != "versions"}

        # Apply template substitution to all fields
        expanded = _apply_version_template(expanded, param_name, i, idx, range_values)

        # Set versioned name
        expanded["name"] = f"{base_name}_{i}"

        # Add version metadata for runtime
        expanded["_version_context"] = {
            "i": i,
            "idx": idx,
            "length": total_versions,
            "first": idx == 0,
            "last": idx == total_versions - 1,
            "base_name": base_name,
            "param_name": param_name,
        }
        # Add custom param name if different from default
        if param_name != "i":
            expanded["_version_context"][param_name] = i

        if render is not None:
            # A setting that reads `i` or `version.*` renders once per version; the prompt
            # was left unmarked for the per-record render, which has these names too.
            version = expanded["_version_context"]
            names = {"version": version}
            names.update({k: version[k] for k in VersionNamespaceBuilder.promoted_names(version)})
            expanded = _render_marked_values(
                expanded, render, names, f"actions[{expanded['name']}]"
            )

        expanded_actions.append(expanded)

    return expanded_actions


def _expand_workflow_versions(data: dict[str, Any], render: MarkedRenderer | None = None) -> None:
    """
    Expand all versioned actions in a workflow.

    Finds actions with 'versions' config and expands them in place.

    Args:
        data: Workflow configuration dict (modified in place)
    """
    actions = data.get("actions", [])
    if not actions:
        return

    expanded_actions = []
    for action in actions:
        if "versions" in action and not action.get("versions"):
            # Declared and empty: it fans out nothing, and until `range` carried a
            # default the missing field was the only thing refusing it.
            name = action.get("name", "unknown")
            raise ConfigurationError(
                f"action '{name}': versions: the block is empty, so it declares no "
                f"versions and fans out nothing; remove it, or give it a range",
                context={"action_name": name, "operation": "expand_versioned_action"},
            )
        if action.get("versions"):
            # Expand versioned action into multiple
            expanded = _expand_versioned_action(action, render)
            expanded_actions.extend(expanded)
            logger.debug(
                "Expanded versioned action '%s' into %d actions",
                action.get("name"),
                len(expanded),
            )
        else:
            expanded_actions.append(action)

    data["actions"] = expanded_actions


def _load_yaml_content(yaml_path, project_root: Path | None = None):
    """
    Load YAML content from file, resolving prompt references if needed.

    Args:
        yaml_path: Path to YAML file
        project_root: Optional project root for prompt file search

    Returns:
        YAML content as string

    Raises:
        ConfigurationError: If file cannot be read or prompt loading fails
    """
    try:
        with open(yaml_path, encoding="utf-8") as yaml_file:
            content = yaml_file.read()
    except (OSError, FileNotFoundError) as e:
        raise ConfigurationError(
            "Error reading YAML configuration file",
            context={"yaml_path": yaml_path, "operation": "file_io"},
            cause=e,
        ) from e

    if content.strip().startswith("$"):
        try:
            content = PromptLoader.load_prompt(content.strip()[1:], project_root=project_root)
        except ValueError as e:
            raise ConfigurationError(
                "Failed to load prompt",
                context={"yaml_path": yaml_path, "operation": "load_prompt"},
                cause=e,
            ) from e

    return content


def render_pipeline_with_templates(
    yaml_path: str | Path,
    templates_folder: str | Path,
    schema_dir: Path | None = None,
    compile_schemas: bool = True,
    strict: bool = False,
    project_root: Path | None = None,
) -> str:
    """
    Render and compile a YAML pipeline configuration.

    This is the single compilation step for workflows.
    After this function, the YAML is fully self-contained with:
    - Every Jinja2 tag the load can resolve rendered; an action's prompt keeps the tags
      only a record or a version can resolve, for the per-record render
    - All prompt references ($prompt_name) resolved
    - All named schemas (schema_name: foo) inlined from schema/ directory
    - All inline schemas expanded to unified format

    Args:
        yaml_path: Path to YAML configuration file
        templates_folder: Path to folder containing Jinja2 templates
        schema_dir: Optional schema directory. Defaults to project_root/schema.
        compile_schemas: Whether to compile/inline schemas (default: True)
        strict: If True, raise errors on schema load failures instead of warnings.
                Use strict=True in CI/CD or production to catch missing schemas early.
        project_root: Optional project root for resolving relative paths.

    Returns:
        Fully compiled YAML content as string, ready for execution

    Raises:
        TemplateRenderingError: If template rendering fails
        ConfigurationError: If YAML parsing or configuration fails, or if strict=True
                           and any schema fails to load
    """
    loader = DeferringFileSystemLoader(str(templates_folder))
    env = Environment(loader=loader, undefined=StrictUndefined)
    env.globals["load_prompt"] = functools.partial(
        PromptLoader.load_prompt, project_root=project_root
    )
    env.filters["dedent"] = textwrap.dedent
    exports = template_folder_exports(env, Path(templates_folder))
    loader.exports = exports
    _load_template_globals(env, str(templates_folder))

    yaml_content = _load_yaml_content(yaml_path, project_root=project_root)

    # Step 1: Jinja2 template rendering. A tag naming what only a record or a version
    # supplies is left in place, marked, for the stage that has the name.
    deferral = defer_unresolved_tags(
        yaml_content,
        env,
        exports.names | set(env.globals),
        exports.carrying,
        include=functools.partial(loader.leaves_tags, env),
    )
    tested = exports.tested | deferral.tested
    if tested:
        names = ", ".join(repr(n) for n in sorted(tested))
        raise TemplateRenderingError(
            f"{names} from templates/ renders a tag only a record supplies, and a tag tests or "
            "filters it at load, where it is still that tag's text. Capture it in the prompt "
            "that tests it, as {% set value %}{{ ... }}{% endset %}, and test the capture",
            context={"yaml_path": str(yaml_path), "templates_folder": str(templates_folder)},
        )
    try:
        rendered_yaml_content = env.from_string(deferral.source).render()
    except jinja2.TemplateError as e:
        raise TemplateRenderingError(
            f"Error rendering YAML template from '{yaml_path}': {safe_format_error(e)}",
            context={"yaml_path": str(yaml_path), "templates_folder": str(templates_folder)},
            cause=e,
        ) from e

    rendered_yaml_content = textwrap.dedent(rendered_yaml_content)

    # Step 2: Parse YAML
    try:
        data = yaml.safe_load(rendered_yaml_content)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        unmarked = strip_marks(rendered_yaml_content)
        try:
            saved_file_msg = _save_failed_render(
                unmarked, Path(yaml_path).stem, project_root=project_root
            )
        except OSError as save_err:
            logger.warning("Could not save failed render output for debugging: %s", save_err)
            saved_file_msg = ""
        problem = getattr(e, "problem", "") or ""
        left = ""
        if is_marked(rendered_yaml_content):
            left = _left_tags_note(deferral.unresolved, deferral.per_record)
        raise ConfigurationError(
            f"Error parsing YAML after template rendering{left}{saved_file_msg}",
            context={
                "yaml_path": str(yaml_path),
                "line": mark.line + 1 if mark else None,
                "column": mark.column + 1 if mark else None,
                "problem": problem + left,
                "operation": "parse_yaml",
                "rendered_content": unmarked,
            },
            cause=e,
        ) from e

    def render(text: str, names: Mapping[str, Any], where: str) -> str:
        try:
            return render_marked(env, text, names)
        except jinja2.TemplateError as e:
            # Not chained: the CLI reports the root cause, and Jinja's alone does not say
            # which value of the file it was rendering.
            raise TemplateRenderingError(
                f"{where or 'a value'}: {safe_format_error(e)}. Only an action's prompt "
                "renders per record, and a versioned action's other values per version",
                context={"yaml_path": str(yaml_path), "value": strip_marks(text)},
            ) from None

    # Step 3: Resolve prompt references
    _strip_prompt_marks(data)
    _resolve_prompt_fields(data, project_root=project_root)

    # Step 4: Expand versioned actions
    if data:
        _expand_workflow_versions(data, render)

    # What is still marked named something only a record supplies, outside a prompt, or
    # something nothing supplies: rendering it now fails the load on that name.
    if isinstance(data, dict) and isinstance(data.get("actions"), list):
        data["actions"] = [
            _render_marked_values(action, render, {}, f"actions[{action.get('name')}]")
            if isinstance(action, dict)
            else action
            for action in data["actions"]
        ]
    data = _render_marked_values(data, render, {}, "")

    # Step 5: Compile schemas (inline named schemas, expand inline dicts)
    if compile_schemas and data:
        _compile_workflow_schemas(data, schema_dir, strict=strict, project_root=project_root)

    return yaml.dump(data, sort_keys=False)
