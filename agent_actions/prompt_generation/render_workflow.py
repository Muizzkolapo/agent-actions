import os
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from agent_actions.prompt_generation.prompt_handler import PromptLoader
from agent_actions.shared.exceptions import TemplateRenderingError, ConfigurationError
import jinja2
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
    dedented = textwrap.dedent(yaml_text)
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
    env.globals['load_prompt'] = PromptLoader.load_prompt
    import textwrap
    env.filters['dedent'] = textwrap.dedent
    template_files = [f for f in os.listdir(templates_folder) if f.endswith(('.j2', '.jinja2'))]
    for template_file in template_files:
        try:
            template = env.get_template(template_file)
            module = template.module
            env.globals.update(vars(module))
        except jinja2.TemplateNotFound:
            print(f"Warning: Template file '{template_file}' not found in {templates_folder}.")
        except jinja2.TemplateSyntaxError as e:
            raise TemplateRenderingError('Syntax error in template', context={'template_file': template_file, 'line': e.lineno, 'message': e.message, 'templates_folder': templates_folder}, cause=e)
        except Exception as e:
            raise TemplateRenderingError(f"Unexpected error loading template '{template_file}': {safe_format_error(e)}", context={'template_file': template_file, 'templates_folder': templates_folder}, cause=e) from e
    try:
        with open(yaml_path, 'r', encoding='utf-8') as yaml_file:
            yaml_content = yaml_file.read()
        if yaml_content.strip().startswith('$'):
            prompt_key = yaml_content.strip()[1:]
            try:
                yaml_content = PromptLoader.load_prompt(prompt_key)
            except ValueError as e:
                raise ConfigurationError('Failed to load prompt', context={'prompt_key': prompt_key, 'yaml_path': yaml_path, 'operation': 'load_prompt'}, cause=e)
        template = env.from_string(yaml_content)
        rendered_yaml_content = template.render()
        rendered_yaml_content = normalize_yaml_indentation(rendered_yaml_content)
        data = yaml.safe_load(rendered_yaml_content)

        def resolve_prompt_fields(item):
            """
            Recursively search for keys named 'prompt' whose values begin with '$' or contain 'return_collection'.
            If found, resolve the prompt using PromptLoader.load_prompt and update the value.
            """
            if isinstance(item, dict):
                for key, value in item.items():
                    if key == 'prompt' and isinstance(value, str):
                        if value.strip().startswith('$'):
                            parts = value.strip().split(maxsplit=1)
                            prompt_key = parts[0][1:]
                            extra = parts[1] if len(parts) > 1 else ''
                            try:
                                resolved = PromptLoader.load_prompt(prompt_key)
                                item[key] = resolved + (' ' + extra if extra else '')
                            except Exception:
                                item[key] = value
                    elif isinstance(value, (dict, list)):
                        resolve_prompt_fields(value)
            elif isinstance(item, list):
                for sub_item in item:
                    resolve_prompt_fields(sub_item)
        resolve_prompt_fields(data)
        rendered_yaml_content = yaml.dump(data, sort_keys=False)
        return rendered_yaml_content
    except FileNotFoundError as e:
        raise ConfigurationError('YAML configuration file not found', context={'yaml_path': yaml_path, 'operation': 'render_template'}, cause=e)
    except IOError as e:
        raise ConfigurationError('IO error reading YAML file', context={'yaml_path': yaml_path, 'operation': 'file_io'}, cause=e)
    except yaml.YAMLError as e:
        problem = getattr(e, 'problem', '')
        mark = getattr(e, 'problem_mark', None)
        workflow_name = Path(yaml_path).stem
        cache_dir = Path.cwd() / '.agent-actions' / 'cache' / 'rendered_workflows'
        cache_dir.mkdir(parents=True, exist_ok=True)
        failed_render_path = cache_dir / f'{workflow_name}_failed.yml'
        try:
            with open(failed_render_path, 'w', encoding='utf-8') as f:
                f.write(rendered_yaml_content)
            saved_file_msg = f'\nRendered output saved to: {failed_render_path}\nDebug with: agent-actions render {workflow_name}'
        except Exception:
            saved_file_msg = ''
        raise ConfigurationError(f'Error parsing YAML after template rendering{saved_file_msg}', context={'yaml_path': yaml_path, 'line': mark.line + 1 if mark else None, 'column': mark.column + 1 if mark else None, 'problem': problem, 'operation': 'parse_yaml'}, cause=e)
    except jinja2.TemplateError as e:
        raise TemplateRenderingError(f"Error rendering YAML template from '{yaml_path}': {safe_format_error(e)}", context={'yaml_path': yaml_path, 'templates_folder': templates_folder}, cause=e) from e
    except Exception as e:
        raise TemplateRenderingError(f"Unexpected error rendering YAML from '{yaml_path}': {safe_format_error(e)}", context={'yaml_path': yaml_path, 'templates_folder': templates_folder}, cause=e) from e