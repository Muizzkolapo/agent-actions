import os
import sys
import yaml
from jinja2 import Environment, FileSystemLoader
from agent_actions.exceptions import raise_template_load_error, raise_yaml_render_error

def render_pipeline_with_templates(yaml_path, templates_folder, output_file=None):
    """
    Render a YAML pipeline configuration by resolving macros from Jinja2 templates.

    :param yaml_path: Path to the input YAML file.
    :param templates_folder: Path to the folder containing Jinja2 templates.
    :param output_file: Path to save the rendered output (optional).
    :return: The rendered YAML as a string.
    """
    env = Environment(loader=FileSystemLoader(templates_folder))
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
        template = env.from_string(yaml_content)
        rendered_yaml_content = template.render()
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as out_file:
                out_file.write(rendered_yaml_content)

        return rendered_yaml_content
    except Exception as e:
        raise_yaml_render_error(yaml_path, str(e))