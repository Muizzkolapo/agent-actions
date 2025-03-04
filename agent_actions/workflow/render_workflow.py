import os
import yaml
from jinja2 import Environment, FileSystemLoader
from agent_actions.workflow.exceptions import raise_template_load_error, raise_yaml_render_error
from agent_actions.handlers.prompt_handler import PromptLoader

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
        except Exception as e:
            raise_template_load_error(template_file, str(e))
    
    try:
        with open(yaml_path, 'r', encoding='utf-8') as yaml_file:
            yaml_content = yaml_file.read()
        
        # If the entire YAML file is just a prompt reference (i.e. starts with '$')
        if yaml_content.strip().startswith('$'):
            prompt_key = yaml_content.strip()[1:]
            yaml_content = PromptLoader.load_prompt(prompt_key)
        
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
    except Exception as e:
        raise_yaml_render_error(yaml_path, str(e))