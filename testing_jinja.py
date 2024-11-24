import jinja2

# YAML Template
yaml_template = """
exam_question_pipeline:
  - agent_type: step_1_scenario_question_generator
    dependencies: []
    api_key: {{ api_key }}
    model_vendor: "openai"
    model_name: "gpt-4o-mini"
    schema_name: question_schema
    use_few_shot_samples: 3
    side_collection: []  
    prompt: $exam_question_pipeline.step_1_scenario_question_generator

  - agent_type: step_2_adversarial_reviewer
    dependencies: [step_1_scenario_question_generator]
    api_key: {{ apikey() | trim }}
    model_vendor: "openai"
    model_name: "gpt-4o-mini"
    schema_name: question_schema
    use_few_shot_samples: 0
    side_collection: []
    prompt: $exam_question_pipeline.step_2_adversarial_reviewer
"""

# Combined Macro Template
macro_template = """
{% macro apikey() -%}
demo
{%- endmacro %}

{% set api_key = "demo" %}
"""

# Create a Jinja2 environment
env = jinja2.Environment(loader=jinja2.DictLoader({'template': yaml_template, 'macros': macro_template}))

# Load and register the macros
macros = env.get_template('macros')
env.globals.update(macros.module.__dict__)  # Expose all macros as globals

# Render the YAML
template = env.get_template('template')
rendered_yaml = template.render()

print(rendered_yaml)
