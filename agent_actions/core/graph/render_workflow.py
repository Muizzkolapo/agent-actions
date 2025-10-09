import os
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from agent_actions.agents.handlers.prompt_handler import PromptLoader
from agent_actions.core.exceptions import TemplateRenderingError, ConfigurationError
import jinja2 # For specific Jinja2 exceptions
from agent_actions.core.safe_format import safe_format_error


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
    import textwrap

    # Remove common leading whitespace
    dedented = textwrap.dedent(yaml_text)

    # Additional normalization if needed
    lines = dedented.splitlines(keepends=True)

    return ''.join(lines)


def render_pipeline_with_templates(yaml_path, templates_folder):
    """
    Render a YAML pipeline configuration by resolving macros from Jinja2 templates.
    This function also processes any prompt fields starting with '$', such as:

        prompt: $code_quiz_generator.code_generation_agent we call or code for rendering the prompt

    By doing so, we ensure that the final YAML includes all resolved information before API calls.
    """
    env = Environment(loader=FileSystemLoader(templates_folder))

    # Make the prompt loader available within Jinja2 templates in case it's needed
    env.globals['load_prompt'] = PromptLoader.load_prompt

    # Add YAML-safe indentation filter
    import textwrap
    env.filters['dedent'] = textwrap.dedent


    template_files = [f for f in os.listdir(templates_folder) if f.endswith(('.j2', '.jinja2'))]
    for template_file in template_files:
        try:
            template = env.get_template(template_file)
            module = template.module
            env.globals.update(vars(module))
        except jinja2.TemplateNotFound:
            # This might be acceptable if some templates are optional, log and continue
            print(f"Warning: Template file '{template_file}' not found in {templates_folder}.")
        except jinja2.TemplateSyntaxError as e:
            raise TemplateRenderingError(
                "Syntax error in template",
                context={'template_file': template_file, 'line': e.lineno, 'message': e.message, 'templates_folder': templates_folder},
                cause=e
            )
        except Exception as e: # Catch other unexpected errors during template loading
            raise TemplateRenderingError(
                f"Unexpected error loading template '{template_file}': {safe_format_error(e)}",
                context={'template_file': template_file, 'templates_folder': templates_folder},
                cause=e
            ) from e
    
    try:
        with open(yaml_path, 'r', encoding='utf-8') as yaml_file:
            yaml_content = yaml_file.read()
        
        # If the entire YAML file is just a prompt reference (i.e. starts with '$')
        if yaml_content.strip().startswith('$'):
            prompt_key = yaml_content.strip()[1:]
            try:
                yaml_content = PromptLoader.load_prompt(prompt_key)
            except ValueError as e: # PromptLoader.load_prompt raises ValueError
                raise ConfigurationError(
                    "Failed to load prompt",
                    context={'prompt_key': prompt_key, 'yaml_path': yaml_path, 'operation': 'load_prompt'},
                    cause=e
                )
        
        template = env.from_string(yaml_content)
        rendered_yaml_content = template.render()

        # Normalize indentation before parsing
        rendered_yaml_content = normalize_yaml_indentation(rendered_yaml_content)

        # Load YAML into a Python structure for further processing
        data = yaml.safe_load(rendered_yaml_content)
        
        def resolve_prompt_fields(item):
            """
            Recursively search for keys named 'prompt' whose values begin with '$' or contain 'return_collection'.
            If found, resolve the prompt using PromptLoader.load_prompt and update the value.
            """
            if isinstance(item, dict):
                for key, value in item.items():
                    if key == 'prompt' and isinstance(value, str):
                        # Handle $ prompt references
                        if value.strip().startswith('$'):
                            parts = value.strip().split(maxsplit=1)
                            prompt_key = parts[0][1:]  # Remove the '$'
                            extra = parts[1] if len(parts) > 1 else ""
                            try:
                                resolved = PromptLoader.load_prompt(prompt_key)
                                item[key] = resolved + (" " + extra if extra else "")
                            except Exception:
                                # If prompt resolution fails, leave the original prompt text.
                                item[key] = value
                        # Handle return_collection syntax - leave as-is for runtime processing
                    elif isinstance(value, (dict, list)):
                        resolve_prompt_fields(value)
            elif isinstance(item, list):
                for sub_item in item:
                    resolve_prompt_fields(sub_item)
        
        # Resolve any prompt references in the YAML structure.
        resolve_prompt_fields(data)
        rendered_yaml_content = yaml.dump(data, sort_keys=False)

        return rendered_yaml_content
    except FileNotFoundError as e:
        raise ConfigurationError(
            "YAML configuration file not found",
            context={'yaml_path': yaml_path, 'operation': 'render_template'},
            cause=e
        )
    except IOError as e:
        raise ConfigurationError(
            "IO error reading YAML file",
            context={'yaml_path': yaml_path, 'operation': 'file_io'},
            cause=e
        )
    except yaml.YAMLError as e:
        problem = getattr(e, 'problem', '')
        mark = getattr(e, 'problem_mark', None)

        # Extract workflow name and save failed render for debugging
        workflow_name = Path(yaml_path).stem
        cache_dir = Path.cwd() / '.agent-actions' / 'cache' / 'rendered_workflows'
        cache_dir.mkdir(parents=True, exist_ok=True)
        failed_render_path = cache_dir / f'{workflow_name}_failed.yml'

        # Save the rendered content that failed to parse
        try:
            with open(failed_render_path, 'w', encoding='utf-8') as f:
                f.write(rendered_yaml_content)
            saved_file_msg = f"\nRendered output saved to: {failed_render_path}\nDebug with: agent-actions render {workflow_name}"
        except Exception:
            saved_file_msg = ""

        raise ConfigurationError(
            f"Error parsing YAML after template rendering{saved_file_msg}",
            context={
                'yaml_path': yaml_path,
                'line': mark.line + 1 if mark else None,
                'column': mark.column + 1 if mark else None,
                'problem': problem,
                'operation': 'parse_yaml'
            },
            cause=e
        )
    except jinja2.TemplateError as e: # Catches TemplateSyntaxError, UndefinedError, etc.
        raise TemplateRenderingError(
            f"Error rendering YAML template from '{yaml_path}': {safe_format_error(e)}",
            context={'yaml_path': yaml_path, 'templates_folder': templates_folder},
            cause=e
        ) from e
    except Exception as e:
        # General catch-all for unexpected issues during rendering or file operations
        raise TemplateRenderingError(
            f"Unexpected error rendering YAML from '{yaml_path}': {safe_format_error(e)}",
            context={'yaml_path': yaml_path, 'templates_folder': templates_folder},
            cause=e
        ) from e