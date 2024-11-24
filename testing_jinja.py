import jinja2

# Load your YAML template
# YAML Template
yaml_template = """
exam_question_pipeline:
  {{ step_1_scenario_question_generator() }}
  {{ step_2_adversarial_reviewer() }}
"""

# Define your macros
macro_template = """
{% macro step_1_scenario_question_generator() %}
- agent_type: step_1_scenario_question_generator
  dependencies: []
  api_key: OPENAI_API_KEY
  model_vendor: openai
  model_name: gpt-4o-mini
  schema_name: question_schema
  use_few_shot_samples: 3
  side_collection: []
  prompt: $exam_question_pipeline.step_1_scenario_question_generator
{% endmacro %}

{% macro step_2_adversarial_reviewer() %}
- agent_type: step_2_adversarial_reviewer
  dependencies: []
  api_key: OPENAI_API_KEY
  model_vendor: openai
  model_name: gpt-4o-mini
  schema_name: question_schema
  use_few_shot_samples: 3
  side_collection: []
  prompt: $exam_question_pipeline.step_2_adversarial_reviewer
{% endmacro %}
"""

# Create a Jinja2 environment
env = jinja2.Environment(loader=jinja2.DictLoader({'template': yaml_template, 'macros': macro_template}))

# Load and register the macros
macros = env.get_template('macros')
env.globals.update({
    'step_1_scenario_question_generator': macros.module.step_1_scenario_question_generator,
    'step_2_adversarial_reviewer': macros.module.step_2_adversarial_reviewer,
})

# Render the YAML
template = env.get_template('template')
rendered_yaml = template.render()

print(rendered_yaml)
