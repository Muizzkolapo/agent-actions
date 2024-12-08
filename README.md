- we have two loaders file loader and list loaders
- make sure we have a loader for textlike files where we chunk
- we have a list loader for csv json ,
- we have formatted prompt
- we have side output
- we have tool calling
- we have dispatch within prompt
- we have importing prompt
- we have return source and some keys retrin collection and source context 
- we have side collection


agent-actions/
├── agent_actions_core/
│   ├── core/
│   ├── processors/
│   ├── vendors/
│   └── __init__.py
├── agent_actions_cli/
│   ├── commands/
│   └── __init__.py
├── agent_actions_web/
│   ├── static/
│   ├── templates/
│   └── __init__.py
├── config/
│   ├── default_config.yml
│   └── agent_actions.yml
├── docs/
│   └── web_interface/
├── tests/
│   ├── unit/
│   └── integration/
├── setup.py
├── requirements.txt
├── README.md
├── MANIFEST.in
└── Makefile





* we had a situation where we had code objects in json and need to load the source along side them into staging, what we did was to create the code and ensure they had guid and we used tooling as the first to extract



- gemini, cohere and,mistral usses the gemini schema format
- Openai has its own schema formatclear


  - agent_type: step_7_dbt_exam_options_reviewer
    dependencies: ['step_6_tool_add_option_lengths']
    api_key: GROQ_API_KEY
    model_vendor: "llama3-8b-8192"
    model_name: "gemini-1.5-flash"
    schema_name: gemini_question
    use_few_shot_samples: 0
    side_collection: []
    prompt: $exam_question_pipeline.step_6_tool_add_option_lengths


    api_key: GEMINI_API_KEY
    model_name: "gemini-1.5-flash"
    model_vendor: "Gemini"

    api_key: MISTRAL_API_KEY
    model_vendor: "mistral"
    model_name: "mistral-large-latest"

    api_key: COHERE_API_KEY
    model_vendor: "cohere"
    model_name: "command-r-plus-08-2024"
    schema_name: gemini_question






sample usage of template
exam_question_pipeline:
  - {{ test() }}
  - agent_type: step_2_adversarial_reviewer
    dependencies: [step_1_scenario_question_generator]
    api_key: {{ api_key }}
    model_vendor: "openai"
    model_name: "gpt-4o-mini"
    schema_name: question_schema
    use_few_shot_samples: 0
    side_collection: []
    prompt: $exam_question_pipeline.step_2_adversarial_reviewer
--macrosfile
{% macro test() -%}
    agent_type: step_1_scenario_question_generator
    dependencies: []
    api_key: OPENAI_API_KEY
    model_vendor: "openai"
    model_name: "gpt-4o-mini"
    schema_name: question_schema
    use_few_shot_samples: 3
    side_collection: []  
    prompt: $exam_question_pipeline.step_1_scenario_question_generator
{%- endmacro %}

{% set api_key = 'OPENAI_API_KEY' %}







-- for a side collection to work the key to be selected needs to be part of the outer key directly under content key
not this anything within key_ideas cant be side collected
        "content": {
            "TITLE": "Searching GitHub Methods and Features",
            "DESCRIPTION": "This section explains the different methods available for searching repositories on GitHub, including global search and scoped search, and their functionalities and limitations.",
            "KEY_IDEAS": [
                {
                    "CONCEPT": "Global Search",
                    "DEFINITION": "A comprehensive search method that allows users to search across all of GitHub, using a complete search syntax to find key terms across multiple result types and repositories.",
                    "EXAMPLES": [
                        "Searching for the term 'sidebar' across GitHub to find related code, issues, and pull requests."
                    ],
                    "LINK": "\\nhttps://learn.microsoft.com/en-gb/training/modules/search-organize-repository-history-github/2-search-organize-repository-history-github\""
                }
            ]
        }

