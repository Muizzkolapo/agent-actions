import os
import sys
import yaml
from jinja2 import Environment, FileSystemLoader
from agent_actions.handlers.file_handler import FileHandler


# When we do agent render exam_question_pipeline we load the template defined by the user and print it out
def get_template_name(agent_config_file):
    with open(agent_config_file, 'r') as f:
        config = yaml.safe_load(f)
        exam_pipeline = config.get('exam_question_pipeline', {})
        template_name = exam_pipeline.get('template_name_tocheck', None)
        
        return template_name

def render_template(agent_config_file):
    template_name = get_template_name(agent_config_file)
    current_dir = os.getcwd()
    template_dir = os.path.join(current_dir, "templates")
    template_file = os.path.join(template_dir, template_name)
    with open(template_file, 'r') as file:
        content = file.read()
    print(content)
    
