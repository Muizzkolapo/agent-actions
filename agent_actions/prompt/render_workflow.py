"""Module for rendering workflow templates with Jinja2 and YAML processing."""

import os
import textwrap
from pathlib import Path

import jinja2
import yaml
from jinja2 import Environment, FileSystemLoader

from agent_actions.errors import TemplateRenderingError, ConfigurationError
from agent_actions.prompt.handler import PromptLoader
from agent_actions.utils.safe_format import safe_format_error


def normalize_yaml_indentation(yaml_text: str) -> str:
    """
    Normalize common YAML indentation issues.

    Fixes:
    - Excessive leading whitespace from macro indentation
    - Inconsistent list item spacing
    - Preserves relative indentation within blocks

    Args:
        yaml_text: Rendered YAML text that may have indentation issues

    Returns:
        Normalized YAML text with consistent indentation

    Example:
        Input:  '      - name: foo\\n        kind: tool'
        Output: '  - name: foo\\n    kind: tool'
    """
    dedented = textwrap.dedent(yaml_text)
    lines = dedented.splitlines(keepends=True)
    return "".join(lines)


def _load_template_globals(env, templates_folder):
    """
    Load and register all Jinja2 templates and their globals.

    Args:
        env: Jinja2 Environment instance
        templates_folder: Path to templates directory
    """
    template_files = [f for f in os.listdir(templates_folder) if f.endswith((".j2", ".jinja2"))]
    for template_file in template_files:
        try:
            template = env.get_template(template_file)
            module = template.module
            env.globals.update(vars(module))
        except jinja2.TemplateNotFound:
            print(f"Warning: Template file '{template_file}' not found in {templates_folder}.")
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
            f"Debug with: agent-actions render {workflow_name}"
        )
    except IOError:
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
                        # Keep original value if loading fails
                        item[key] = value
            elif isinstance(value, (dict, list)):
                _resolve_prompt_fields(value)
    elif isinstance(item, list):
        for sub_item in item:
            _resolve_prompt_fields(sub_item)


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
        with open(yaml_path, "r", encoding="utf-8") as yaml_file:
            content = yaml_file.read()
    except (FileNotFoundError, IOError) as e:
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


def render_pipeline_with_templates(yaml_path, templates_folder):
    """
    Render a YAML pipeline configuration with Jinja2 templates.

    This function resolves Jinja2 macros and processes prompt fields
    starting with '$' by loading them via PromptLoader.load_prompt.

    Args:
        yaml_path: Path to YAML configuration file
        templates_folder: Path to folder containing Jinja2 templates

    Returns:
        Rendered YAML content as string

    Raises:
        TemplateRenderingError: If template rendering fails
        ConfigurationError: If YAML parsing or configuration fails
    """
    env = Environment(loader=FileSystemLoader(templates_folder))
    env.globals["load_prompt"] = PromptLoader.load_prompt
    env.filters["dedent"] = textwrap.dedent
    _load_template_globals(env, templates_folder)

    yaml_content = _load_yaml_content(yaml_path)

    try:
        rendered_yaml_content = env.from_string(yaml_content).render()
    except jinja2.TemplateError as e:
        raise TemplateRenderingError(
            f"Error rendering YAML template from '{yaml_path}': {safe_format_error(e)}",
            context={"yaml_path": yaml_path, "templates_folder": templates_folder},
            cause=e,
        ) from e

    rendered_yaml_content = normalize_yaml_indentation(rendered_yaml_content)

    try:
        data = yaml.safe_load(rendered_yaml_content)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        saved_file_msg = _save_failed_render(rendered_yaml_content, Path(yaml_path).stem)
        raise ConfigurationError(
            f"Error parsing YAML after template rendering{saved_file_msg}",
            context={
                "yaml_path": yaml_path,
                "line": mark.line + 1 if mark else None,
                "column": mark.column + 1 if mark else None,
                "problem": getattr(e, "problem", ""),
                "operation": "parse_yaml",
                "rendered_content": rendered_yaml_content,
            },
            cause=e,
        ) from e

    _resolve_prompt_fields(data)
    return yaml.dump(data, sort_keys=False)
