import os
import yaml
from jinja2 import Environment, FileSystemLoader
from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.cli.exceptions import TemplateRenderingError, ConfigurationError
import jinja2 # For specific Jinja2 exceptions

def render_pipeline_with_templates(yaml_path, templates_folder, output_file=None):
    """
    Render a YAML pipeline configuration by resolving macros from Jinja2 templates.
    This function also processes any prompt fields starting with '$', such as:
    
        prompt: $code_quiz_generator.code_generation_agent we call or code for rendering the prompt
    
    By doing so, we ensure that the final YAML includes all resolved information before API calls.
    """
    env = Environment(loader=FileSystemLoader(templates_folder))
    
    # Make the prompt loader available within Jinja2 templates in case it's needed
    env.globals['load_prompt'] = PromptLoader.load_prompt
    
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
            raise TemplateRenderingError(f"Syntax error in template '{template_file}': {e.message} (line {e.lineno})") from e
        except Exception as e: # Catch other unexpected errors during template loading
            raise TemplateRenderingError(f"Unexpected error loading template '{template_file}': {str(e)}") from e
    
    try:
        with open(yaml_path, 'r', encoding='utf-8') as yaml_file:
            yaml_content = yaml_file.read()
        
        # If the entire YAML file is just a prompt reference (i.e. starts with '$')
        if yaml_content.strip().startswith('$'):
            prompt_key = yaml_content.strip()[1:]
            try:
                yaml_content = PromptLoader.load_prompt(prompt_key)
            except ValueError as e: # PromptLoader.load_prompt raises ValueError
                raise ConfigurationError(f"Failed to load prompt '{prompt_key}' referenced in '{yaml_path}': {e}") from e
        
        template = env.from_string(yaml_content)
        rendered_yaml_content = template.render()
        
        # Load YAML into a Python structure for further processing
        data = yaml.safe_load(rendered_yaml_content)
        
        def resolve_prompt_fields(item):
            """
            Recursively search for keys named 'prompt' whose values begin with '$'.
            If found, resolve the prompt using PromptLoader.load_prompt and update the value.
            """
            if isinstance(item, dict):
                for key, value in item.items():
                    if key == 'prompt' and isinstance(value, str) and value.strip().startswith('$'):
                        # Extract the prompt key (e.g., 'code_quiz_generator.code_generation_agent')
                        # and any extra text after it.
                        parts = value.strip().split(maxsplit=1)
                        prompt_key = parts[0][1:]  # Remove the '$'
                        extra = parts[1] if len(parts) > 1 else ""
                        try:
                            resolved = PromptLoader.load_prompt(prompt_key)
                            item[key] = resolved + (" " + extra if extra else "")
                        except Exception:
                            # If prompt resolution fails, leave the original prompt text.
                            item[key] = value
                    elif isinstance(value, (dict, list)):
                        resolve_prompt_fields(value)
            elif isinstance(item, list):
                for sub_item in item:
                    resolve_prompt_fields(sub_item)
        
        # Resolve any prompt references in the YAML structure.
        resolve_prompt_fields(data)
        rendered_yaml_content = yaml.dump(data, sort_keys=False)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as out_file:
                out_file.write(rendered_yaml_content)
        return rendered_yaml_content
    except FileNotFoundError as e:
        raise ConfigurationError(f"YAML configuration file not found: {yaml_path}") from e
    except IOError as e:
        raise ConfigurationError(f"IO error reading or writing YAML file '{yaml_path}' or output '{output_file}': {e}") from e
    except yaml.YAMLError as e:
        problem = getattr(e, 'problem', '')
        mark = getattr(e, 'problem_mark', None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ConfigurationError(f"Error parsing YAML from '{yaml_path}'{location}: {problem}") from e
    except jinja2.TemplateError as e: # Catches TemplateSyntaxError, UndefinedError, etc.
        raise TemplateRenderingError(f"Error rendering YAML template from '{yaml_path}': {str(e)}") from e
    except Exception as e:
        # General catch-all for unexpected issues during rendering or file operations
        raise TemplateRenderingError(f"Unexpected error rendering YAML from '{yaml_path}': {str(e)}") from e