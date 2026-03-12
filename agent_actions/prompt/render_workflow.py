"""Render and compile workflow templates into self-contained YAML."""

import logging
import textwrap
from pathlib import Path
from typing import Any

import jinja2
import yaml
from jinja2 import Environment, FileSystemLoader

from agent_actions.errors import ConfigurationError, TemplateRenderingError
from agent_actions.prompt.handler import PromptLoader
from agent_actions.utils.safe_format import safe_format_error

logger = logging.getLogger(__name__)


def _load_template_globals(env, templates_folder):
    """
    Load and register all Jinja2 templates and their globals.

    Args:
        env: Jinja2 Environment instance
        templates_folder: Path to templates directory
    """
    templates_path = Path(templates_folder)
    template_files = [p.name for p in templates_path.iterdir() if p.suffix in (".j2", ".jinja2")]
    for template_file in template_files:
        try:
            template = env.get_template(template_file)
            module = template.module
            env.globals.update(vars(module))
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


def _save_failed_render(rendered_yaml_content, workflow_name):
    """
    Save failed render output to cache for debugging.

    Args:
        rendered_yaml_content: The rendered YAML that failed to parse
        workflow_name: Name of the workflow for the cache filename

    Returns:
        Error message string or empty string if save fails
    """
    cache_dir = Path.cwd() / ".agent-actions" / "cache" / "rendered_workflows"
    cache_dir.mkdir(parents=True, exist_ok=True)
    failed_render_path = cache_dir / f"{workflow_name}_failed.yml"
    try:
        with open(failed_render_path, "w", encoding="utf-8") as f:
            f.write(rendered_yaml_content)
        return (
            f"\nRendered output saved to: {failed_render_path}\n"
            f"Debug with: agac render {workflow_name}"
        )
    except OSError:
        return ""


def _resolve_prompt_fields(item):
    """
    Recursively resolve prompt fields starting with '$'.

    Searches for keys named 'prompt' whose values begin with '$'
    and resolves them using PromptLoader.load_prompt.

    Args:
        item: Dictionary, list, or other value to process
    """
    if isinstance(item, dict):
        for key, value in item.items():
            if key == "prompt" and isinstance(value, str):
                if value.strip().startswith("$"):
                    parts = value.strip().split(maxsplit=1)
                    prompt_key = parts[0][1:]
                    extra = parts[1] if len(parts) > 1 else ""
                    try:
                        resolved = PromptLoader.load_prompt(prompt_key)
                        item[key] = resolved + (" " + extra if extra else "")
                    except ValueError:
                        logger.warning(
                            "Failed to resolve prompt reference '%s'; keeping original value",
                            value,
                        )
                        item[key] = value
            elif isinstance(value, (dict, list)):
                _resolve_prompt_fields(value)
    elif isinstance(item, list):
        for sub_item in item:
            _resolve_prompt_fields(sub_item)


# =============================================================================
# Schema Compilation Functions
# =============================================================================


def _load_named_schema(schema_name: str, schema_dir: Path | None = None) -> dict[str, Any]:
    """
    Load a named schema from the schema/ directory.

    Args:
        schema_name: Name of the schema (without .yml extension)
        schema_dir: Optional schema directory. Defaults to cwd/schema.

    Returns:
        Schema data as dictionary

    Raises:
        ConfigurationError: If schema file not found
    """
    if schema_dir is None:
        schema_dir = Path.cwd() / "schema"

    schema_file = schema_dir / f"{schema_name}.yml"

    if not schema_file.exists():
        raise ConfigurationError(
            f"Schema file '{schema_name}.yml' not found",
            context={
                "schema_name": schema_name,
                "schema_dir": str(schema_dir),
                "expected_path": str(schema_file),
                "operation": "load_named_schema",
                "hint": "Ensure the schema file exists in the schema/ directory",
            },
        )

    with open(schema_file, encoding="utf-8") as f:
        return yaml.safe_load(f)


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

    Returns:
        Action with compiled schema (modified in place and returned)
    """
    action_name = action.get("name", "unknown")

    # Handle schema_name: "foo" -> load and inline
    schema_name = action.get("schema_name")
    if schema_name and isinstance(schema_name, str):
        try:
            loaded_schema = _load_named_schema(schema_name, schema_dir)
            action["schema"] = loaded_schema
            del action["schema_name"]
            logger.debug("Inlined named schema '%s' for action '%s'", schema_name, action_name)
        except ConfigurationError as e:
            error_msg = f"Action '{action_name}': Could not load schema '{schema_name}' - {e}"
            if strict and errors is not None:
                errors.append(error_msg)
            else:
                logger.warning("Could not load schema '%s' for inlining", schema_name)

    # Handle schema: "foo" (string reference) -> load and inline
    schema_value = action.get("schema")
    if schema_value and isinstance(schema_value, str):
        try:
            loaded_schema = _load_named_schema(schema_value, schema_dir)
            action["schema"] = loaded_schema
            logger.debug("Inlined schema reference '%s' for action '%s'", schema_value, action_name)
        except ConfigurationError as e:
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

    return action


def _compile_workflow_schemas(
    data: dict[str, Any],
    schema_dir: Path | None = None,
    strict: bool = False,
) -> None:
    """
    Compile all schemas in a workflow configuration.

    Processes both top-level actions and actions within defaults.

    Args:
        data: Workflow configuration dict (modified in place)
        schema_dir: Optional schema directory
        strict: If True, raise ConfigurationError on any schema load failure

    Raises:
        ConfigurationError: If strict=True and any schema fails to load
    """
    errors: list[str] = []

    # Compile schemas in actions list
    actions = data.get("actions", [])
    for action in actions:
        _compile_action_schemas(action, schema_dir, strict=strict, errors=errors)

    # Compile schemas in defaults if present
    defaults = data.get("defaults", {})
    if defaults:
        _compile_action_schemas(defaults, schema_dir, strict=strict, errors=errors)

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
    value: Any, param_name: str, current_val: int, idx: int, values: list[int]
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


def _expand_versioned_action(action: dict[str, Any]) -> list[dict[str, Any]]:
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
    version_config = action.get("versions", {})
    param_name = version_config.get("param", "i")
    version_range = version_config.get("range", [1, 1])

    # Calculate range values
    if len(version_range) == 2:
        start, end = version_range
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

        expanded_actions.append(expanded)

    return expanded_actions


def _expand_workflow_versions(data: dict[str, Any]) -> None:
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
        if action.get("versions"):
            # Expand versioned action into multiple
            expanded = _expand_versioned_action(action)
            expanded_actions.extend(expanded)
            logger.debug(
                "Expanded versioned action '%s' into %d actions",
                action.get("name"),
                len(expanded),
            )
        else:
            expanded_actions.append(action)

    data["actions"] = expanded_actions


def _load_yaml_content(yaml_path):
    """
    Load YAML content from file, resolving prompt references if needed.

    Args:
        yaml_path: Path to YAML file

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
            content = PromptLoader.load_prompt(content.strip()[1:])
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
) -> str:
    """
    Render and compile a YAML pipeline configuration.

    This is the single compilation step for workflows.
    After this function, the YAML is fully self-contained with:
    - All Jinja2 templates resolved
    - All prompt references ($prompt_name) resolved
    - All named schemas (schema_name: foo) inlined from schema/ directory
    - All inline schemas expanded to unified format

    Args:
        yaml_path: Path to YAML configuration file
        templates_folder: Path to folder containing Jinja2 templates
        schema_dir: Optional schema directory. Defaults to cwd/schema.
        compile_schemas: Whether to compile/inline schemas (default: True)
        strict: If True, raise errors on schema load failures instead of warnings.
                Use strict=True in CI/CD or production to catch missing schemas early.

    Returns:
        Fully compiled YAML content as string, ready for execution

    Raises:
        TemplateRenderingError: If template rendering fails
        ConfigurationError: If YAML parsing or configuration fails, or if strict=True
                           and any schema fails to load
    """
    env = Environment(loader=FileSystemLoader(str(templates_folder)))
    env.globals["load_prompt"] = PromptLoader.load_prompt
    env.filters["dedent"] = textwrap.dedent
    _load_template_globals(env, str(templates_folder))

    yaml_content = _load_yaml_content(yaml_path)

    # Step 1: Jinja2 template rendering
    try:
        rendered_yaml_content = env.from_string(yaml_content).render()
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
        saved_file_msg = _save_failed_render(rendered_yaml_content, Path(yaml_path).stem)
        raise ConfigurationError(
            f"Error parsing YAML after template rendering{saved_file_msg}",
            context={
                "yaml_path": str(yaml_path),
                "line": mark.line + 1 if mark else None,
                "column": mark.column + 1 if mark else None,
                "problem": getattr(e, "problem", ""),
                "operation": "parse_yaml",
                "rendered_content": rendered_yaml_content,
            },
            cause=e,
        ) from e

    # Step 3: Resolve prompt references
    _resolve_prompt_fields(data)

    # Step 4: Expand versioned actions
    if data:
        _expand_workflow_versions(data)

    # Step 5: Compile schemas (inline named schemas, expand inline dicts)
    if compile_schemas and data:
        _compile_workflow_schemas(data, schema_dir, strict=strict)

    return yaml.dump(data, sort_keys=False)
