# Sequence Quiz Workflow

## Overview
Generates drag-and-drop sequential ordering quizzes where users arrange items (commands, steps, code blocks) in the correct order.

## Quiz Format (from Image #1)
- **Question**: "Arrange these dbt commands in the correct order for a typical development workflow:"
- **Format**: Draggable items with grip handles (:::)
- **User Task**: Drag and drop items to arrange them in the correct sequence
- **Features**:
  - Visual numbering (1, 2, 3, 4)
  - Item descriptions (e.g., "Execute model transformations")
  - Drag handles for reordering

## Use Cases

### Common Sequence Types:
1. **Workflow Steps** - Development workflows, deployment processes
2. **Commands** - CLI commands that must be executed in order (dbt, git, docker)
3. **Code Execution** - Function calls, initialization sequences
4. **Data Pipeline** - ETL steps, data transformation sequences
5. **Deployment Steps** - CI/CD pipeline stages

## Workflow Steps

### 1. **code_extractor**
- Extracts code blocks or sequential content from documentation
- Uses existing `$drop_down_quiz.Code_extraction` prompt
- Output: `candidate_code_list`

### 2. **flatten_code**
- Flattens extracted code for processing
- Tool: `drop_down_quiz.flatten_code.flatten_code`

### 3. **sequence_scenario_generator**
- Generates realistic scenario explaining why sequence matters
- Output:
  - `sample_usage_scenario`: When/why this sequence is used
  - `code_for_scenario`: The complete correct sequence
  - `scenario_complexity`: Difficulty level
  - `key_considerations`: Why order matters
  - `sequence_type`: Type of sequence (workflow_steps, commands, etc.)

### 4. **extract_sequence_items**
- Breaks down content into 4-6 individual sequential items
- Output: `sequence_items` array with:
  - `item_number`: Position in correct sequence (1, 2, 3...)
  - `item_content`: The actual command/step/code
  - `item_description`: What this item does
  - `why_this_position`: Why it must be here (dependencies)

### 5. **generate_distractors_sequence**
- Identifies common ordering mistakes
- Output: `common_mistakes` array with:
  - `mistake_description`: The incorrect ordering
  - `why_incorrect`: Technical reason it's wrong
  - `consequence`: What happens with wrong order

### 6. **create_explanation**
- Generates comprehensive explanation of correct sequence
- Output:
  - `correct_sequence_explanation`: Step-by-step explanation
  - `key_dependencies`: Critical dependencies between steps
  - `best_practices`: Tips and patterns for remembering order

## Example Data Flow

### Input (from documentation):
```bash
dbt deps
dbt run
dbt test
dbt docs generate
```

### After extract_sequence_items:
```json
{
  "sequence_items": [
    {
      "item_number": 1,
      "item_content": "dbt deps",
      "item_description": "Install package dependencies",
      "why_this_position": "Dependencies must be installed before any dbt commands can run"
    },
    {
      "item_number": 2,
      "item_content": "dbt run",
      "item_description": "Execute model transformations",
      "why_this_position": "Models must be built before they can be tested"
    },
    {
      "item_number": 3,
      "item_content": "dbt test",
      "item_description": "Run data quality tests",
      "why_this_position": "Tests validate models after they're built"
    },
    {
      "item_number": 4,
      "item_content": "dbt docs generate",
      "item_description": "Generate documentation",
      "why_this_position": "Documentation is generated from completed models and tests"
    }
  ]
}
```

### After generate_distractors_sequence:
```json
{
  "common_mistakes": [
    {
      "mistake_description": "Running 'dbt test' before 'dbt run'",
      "why_incorrect": "Tests validate models that haven't been built yet",
      "consequence": "Tests will fail because models don't exist in target schema"
    },
    {
      "mistake_description": "Running 'dbt run' before 'dbt deps'",
      "why_incorrect": "Package dependencies are not installed",
      "consequence": "dbt run will fail with missing dependency errors"
    }
  ]
}
```

## Key Differences from drop_down_quiz

### Similarities (reused):
- ✅ Code extraction
- ✅ Flatten code
- ✅ Scenario generation

### Differences (new):
- ❌ NO blanking (no fill-in-the-blank)
- ❌ NO wrong answer options per blank
- ✅ Complete items that must be reordered
- ✅ Focus on dependencies and flow
- ✅ Common ordering mistakes instead of wrong answers

## Future Tools Needed (for Thinkific formatting)

### `tools/sequence_quiz/format_thinkific.py`
- Will shuffle the correct sequence items
- Generate drag-and-drop HTML/JavaScript
- Format for Thinkific LMS
- Include explanations and feedback

**Note**: Thinkific formatting tool not included in this workflow yet. This workflow only generates the sequence data.

## Output Structure (ready for formatting)

```json
{
  "sample_usage_scenario": "Setting up a dbt project for the first time...",
  "sequence_type": "commands",
  "sequence_items": [...],
  "common_mistakes": [...],
  "correct_sequence_explanation": "The correct sequence ensures...",
  "key_dependencies": [
    "dbt deps must run first to install packages",
    "dbt run requires deps to be installed",
    "dbt test requires models to exist"
  ],
  "best_practices": [
    "Always run dbt deps after updating packages.yml",
    "Run dbt test after dbt run to validate transformations"
  ]
}
```

## Thinkific Considerations

**Challenge**: Drag-and-drop requires JavaScript, but Thinkific has limited JS support.

**Potential Solutions**:
1. Use native HTML5 drag-and-drop API (may work in Thinkific)
2. Fallback: Number-based selection (user enters numbers 1-4 for order)
3. Alternative: Dropdown per position (Position 1: select item, Position 2: select item...)

This will be addressed when creating the Thinkific formatting tool.
