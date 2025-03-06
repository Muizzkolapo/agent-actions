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






---this is the sample data when processing at a file level
{
    'data': [
        {
            'guid': '412fceb5-2e06-488c-9274-d5f4b7034e36',
            'content': [
                {'what_to_test_for': 'Understanding of GitHub search methods (global vs context search).'},
                {'what_to_test_for': "Knowledge of GitHub's search syntax and how to apply search filters effectively."},
                {'what_to_test_for': 'Ability to utilize the `git blame` command to track commit history and contributions to a file.'},
                {'what_to_test_for': "Distinguishing between different types of search results (e.g., code, issues, pull requests) when using GitHub's search functions."},
                {'what_to_test_for': 'Familiarity with using advanced search options to refine search results on GitHub.'}
            ]
        },
        {
            'guid': '2146889e-cc00-4f38-b67e-fdc945dde82c',
            'content': [
                {'what_to_test_for': "Understanding 'git blame' functionality and its user interface on GitHub"},
                {'what_to_test_for': 'Methods to access the blame view in GitHub'},
                {'what_to_test_for': 'Importance of linking issues, commits, and other elements in collaborative projects'},
                {'what_to_test_for': 'Usage of autolinked references and their impact on project documentation'},
                {'what_to_test_for': 'Functionality and benefits of using @mentions in discussions on GitHub'}
            ]
        }
    ]
}



-- when using tool json loads for input and json dumps for output

-- conditional clause can not be used at start of the agent workflow for reprocess to work on an object condition needs to return -> True
- sideoutout cannot be used too













```markdown
# Unified Schema Definition Guide

Your unified schema file is the cornerstone for configuring how our dynamic agent validates and processes inputs. This file is written in YAML (or JSON) and is transformed by our tool into a JSON Schema for target systems like OpenAI or Anthropic.

## Structure Overview
A unified schema consists of two main parts:

- **Name**: The identifier for the schema.
- **Fields**: An array of field definitions that outline each property, including its type and any additional constraints.

When compiled for a target system (for example, OpenAI), the unified schema is transformed into a JSON Schema similar to:

```json
{
  "name": "YourSchemaName",
  "schema": {
    "type": "object",
    "properties": {
      "field1": { "type": "string" },
      "field2": { "type": "array", "items": { "type": "string" } }
    },
    "required": ["field1", "field2"],
    "additionalProperties": false
  }
}
```

## Unified Schema Definition
The unified schema uses familiar JSON Schema vocabulary. Below is an example that defines a simple schema:

```yaml
name: KeyIdeaMapper
fields:
  - id: Key_idea_explanation
    type: string
    required: true
  - id: usage_scenarios
    type: string
    required: true
```

## Field Attributes
Each field in the fields array supports both our unified schema definitions as well as standard JSON Schema terms. Here’s a breakdown of the expected attributes:

### **id (string, required)**
The unique identifier for the field. This will be the key in the generated JSON schema.
- **JSON Schema equivalent**: Used as the property name in "properties".

### **type (string, required)**
Defines the data type of the field. Supported types include "string", "number", "integer", "boolean", "object", and "array".
- **JSON Schema equivalent**: This directly corresponds to the "type" keyword.

### **required (boolean, optional)**
If set to true, the field’s id will be added to the "required" array in the final JSON Schema.

### **items (object, optional)**
If the field is an "array", the items attribute describes the schema for each item in the array.
- **JSON Schema equivalent**: This is used within an array type definition to specify "items".

### **enum (array, optional)**
Specifies a fixed set of acceptable values for the field.
- **JSON Schema equivalent**: This directly maps to the "enum" keyword in JSON Schema.

### **validators (array, optional)**
Allows you to define custom validation rules. For instance, you can specify rules using the "not" keyword to exclude values. Optionally, you can also provide an "errorMessage" for when validation fails.
- **JSON Schema equivalent**: This can translate to constraints like "minimum", "maximum", "pattern", or even custom keywords defined by JSON Schema extensions.

### **mappings (object, optional)**
Provides target-system-specific field names. The keys are the lowercased names of the target systems (e.g., openai, anthropic), and the value is the identifier that should be used in the final schema.

#### **Usage note:** If no mapping is provided for the target system, the original id is used.

## Standard JSON Schema Terms and How to Define Them
In addition to our unified schema attributes, users are encouraged to use standard JSON Schema terminology for constraints and validations:

### **type:**
Specifies the type of data (e.g., "string", "number", "object", "array").

### **properties:**
When the type is "object", define its properties using a mapping. Our tool builds this automatically from your fields array.

### **required:**
An array of property names that must be present. In our unified schema, marking a field as required (`required: true`) automatically includes its id in this list.

### **additionalProperties:**
Set to false to disallow any properties not defined in the schema. This is included by default in the compiled schema.

### **items:**
When defining an array, use "items" to specify the schema for each element. For example:

```yaml
- id: what_to_test_for
  type: array
  items:
    type: string
  required: true
```

### **enum:**
Use "enum" to specify a list of valid values.

### **Validation Keywords:**
Beyond basic types, JSON Schema supports keywords such as:

- `minimum` and `maximum` for numeric ranges.
- `minLength` and `maxLength` for strings.
- `pattern` for regex-based validation.

You can include these constraints via our `validators` attribute in your unified schema. For example:

```yaml
- id: age
  type: number
  validators:
    - not: { minimum: 0 }
      errorMessage: "Age must be a positive number"
```

By combining these JSON Schema keywords with our unified schema format, you have a powerful way to specify exactly how your input data should be structured and validated.

## Example: A More Complex Schema

```yaml
name: TestInsight_Builder
fields:
  - id: what_to_test_for
    type: array
    items:
      type: string
    required: true
  - id: status
    type: string
    enum: [active, inactive, pending]
    required: true
  - id: age
    type: number
    validators:
      - not: { minimum: 0 }
        errorMessage: "Age must be a positive number"
  - id: first_name
    type: string
    mappings:
      openai: firstName
      anthropic: first_name
```

### **Compiled JSON Schema Example**

```json
{
  "name": "TestInsight_Builder",
  "schema": {
    "type": "object",
    "properties": {
      "what_to_test_for": {
        "type": "array",
        "items": { "type": "string" }
      },
      "status": {
        "type": "string",
        "enum": ["active", "inactive", "pending"]
      },
      "age": {
        "type": "number",
        "not": { "minimum": 0 },
        "errorMessage": "Age must be a positive number"
      },
      "firstName": { "type": "string" }
    },
    "required": ["what_to_test_for", "status", "age", "firstName"],
    "additionalProperties": false
  }
}
```

## Summary
- **Unified Schema Format:** Define your schema in YAML/JSON using `name` and `fields`.
- **Field Attributes:** Use `id`, `type`, `required`, `items`, `enum`, `validators`, and `mappings` to specify field details.
- **Standard JSON Schema Terms:** Leverage JSON Schema keywords such as `type`, `properties`, `required`, `additionalProperties`, `items`, and `enum` to create robust validation rules.
- **Compilation Process:** Your unified schema is processed by our tool into a target-specific JSON Schema, ensuring compatibility with different model vendors like OpenAI or Anthropic.

For additional details on JSON Schema, you may refer to the JSON Schema official documentation.
```

