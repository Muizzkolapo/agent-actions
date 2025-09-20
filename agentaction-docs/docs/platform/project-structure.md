# Project Structure

Learn how to organize Agent Actions projects for maximum reusability and maintainability. This guide uses a proven structure from a production enterprise customer who built a complex content generation platform with multiple workflows and shared components.

## Core Project Layout

Every Agent Actions project follows this foundational structure:

```
my-agent-project/
├── agent_actions.yml           # Platform configuration
├── agent_workflow/             # Individual workflow definitions
├── schema/                     # Shared JSON schemas
├── prompt_store/              # Reusable prompts
├── tools/                     # Custom Python functions
├── templates/                 # Jinja2 workflow templates
└── rendered_workflows/        # Generated final workflows
```

## Real-World Example: Enterprise Platform Structure

Here's how a production customer organized their content generation platform:

```
enterprise-platform/
├── agent_actions.yml                    # Platform config
├── agent_workflow/                      # Multiple workflow types
│   ├── content_extraction/              # Content extraction workflow
│   │   ├── agent_config/
│   │   └── agent_io/
│   ├── document_analysis/               # Document analysis workflow
│   │   ├── agent_config/
│   │   └── agent_io/
│   ├── content_generation/              # Main content pipeline
│   │   ├── agent_config/
│   │   └── agent_io/
│   └── content_processing/              # Content processing workflows
│       ├── TextToContentPipeline/
│       ├── structured_content_gen/
│       └── batch_content_gen/
├── schema/                              # Shared across all workflows
│   ├── content_extraction/
│   │   ├── ExtractedContent.yml
│   │   ├── ContentMetadata.yml
│   │   └── content_validation.yml
│   ├── content_generation/
│   │   ├── GenerationRequest_schema.yml
│   │   └── generated_content.yml
│   └── document_processing/
│       └── document_schema.yml
├── prompt_store/                        # Reusable prompts
│   ├── TextToContentPipeline/
│   ├── content_extraction/
│   └── content_generation/
├── tools/                               # Custom Python extensions
│   ├── content_extraction/
│   ├── content_generation/
│   ├── content_validation.py
│   └── format_converters.py
├── templates/                           # Dynamic workflow generation
│   └── content_workflow.jinja2
└── rendered_workflows/                  # Final compiled workflows
    ├── content_extraction.yml
    └── content_generation.yml
```

**Key insight**: This enterprise customer built **4 different workflow types** that all share schemas, prompts, and tools — demonstrating the platform approach.

## Essential Files and Directories

### `agent_actions.yml` - Platform Configuration

The heart of your Agent Actions project. Defines global settings used across all workflows:

```yaml
default_agent_config:
  api_key: OPENAI_API_KEY
  model_name: gpt-4o-mini
  ephemeral: false
  prompt_debug: False
tool: ["tools"]
```

**Purpose**:
- Global model settings
- API configurations
- Tool discovery paths
- Default agent behaviors

### `agent_workflow/` - Workflow Definitions

Each subdirectory represents a distinct workflow pipeline:

```
agent_workflow/
├── content_extraction/          # 3-agent pipeline
├── data_validation/            # 5-agent pipeline
└── content_generation/         # 15-agent pipeline
```

**Structure per workflow**:
```
content_generation/
├── agent_config/               # Agent-specific configs
└── agent_io/                   # Input/output data
    └── few_shot_samples/       # Training examples
```

### `schema/` - Shared Data Contracts

JSON schema definitions that ensure consistent data flow:

```
schema/
├── shared/                     # Common schemas
│   ├── base_response.yml
│   └── error_handling.yml
├── content_extraction/         # Workflow-specific
│   └── extracted_content.yml
└── content_generation/
    ├── content_schema.yml
    └── generated_content.yml
```

**Benefits**:
- Validates agent outputs
- Prevents downstream failures
- Enables schema reuse across workflows
- Self-documenting data contracts

### `prompt_store/` - Reusable Prompts

Centralized prompt management with version control:

```
prompt_store/
├── content_extraction/
│   └── extract_content.md
├── content_generation/
│   └── scenario_generator.md
└── shared/
    └── output_formatting.md
```

**Example prompt file**:
```markdown
# Content Extraction Prompt

Extract structured information from documents...

## Output Schema
Use schema: extracted_content

## Examples
[Few-shot examples here]
```

### `tools/` - Custom Python Functions

Extend Agent Actions with custom processing logic:

```
tools/
├── __init__.py
├── validation/
│   ├── content_validators.py
│   └── schema_checkers.py
├── processing/
│   ├── text_cleaners.py
│   └── format_converters.py
└── integrations/
    ├── external_apis.py
    └── database_connectors.py
```

**Tool structure**:
```python
# tools/validation/content_validators.py
def validate_content_format(content_data):
    """Custom validation for content format"""
    # Your logic here
    return validated_data
```

### `templates/` - Dynamic Workflow Generation

Jinja2 templates for generating workflows programmatically:

```
templates/
├── batch_processing.jinja2     # For bulk operations
├── content_pipeline.jinja2     # Content workflows
└── validation_chain.jinja2     # Quality checks
```

**Example template**:
```yaml
# templates/content_pipeline.jinja2
{% for step in pipeline_steps %}
- agent_type: {{ step.type }}
  dependencies: {{ step.deps }}
  schema_name: {{ step.schema }}
{% endfor %}
```

### `rendered_workflows/` - Compiled Final Workflows

Generated workflows ready for execution:

```
rendered_workflows/
├── production_content_gen.yml  # From template
├── batch_content_extract.yml   # From template
└── validation_pipeline.yml     # From template
```

## Organizing Multiple Workflows

### Pattern 1: By Function

Organize workflows by what they accomplish:

```
agent_workflow/
├── extraction/                 # Data extraction workflows
├── generation/                # Content generation workflows
├── validation/                # Quality assurance workflows
└── transformation/            # Data processing workflows
```

### Pattern 2: By Domain

Organize workflows by business domain:

```
agent_workflow/
├── education/                 # Learning, curriculum workflows
├── content/                   # Blog, documentation workflows
├── analysis/                  # Research, evaluation workflows
└── customer_service/          # Support, FAQ workflows
```

### Pattern 3: By Complexity

Organize workflows by agent count/complexity:

```
agent_workflow/
├── simple/                    # 1-3 agent workflows
├── medium/                    # 4-8 agent workflows
└── complex/                   # 9+ agent workflows
```

## Component Reuse Strategy

### Schema Inheritance

Create base schemas that workflows extend:

```yaml
# schema/shared/base_response.yml
base_response:
  type: object
  properties:
    status: {type: string}
    timestamp: {type: string}

# schema/extraction/content_response.yml
content_response:
  allOf:
    - $ref: "../shared/base_response.yml"
    - properties:
        content: {type: array}
```

### Prompt Composition

Build complex prompts from reusable parts:

```markdown
# prompt_store/shared/output_format.md
Always format output as valid JSON matching the provided schema.

# prompt_store/extraction/content_extractor.md
{include: ../shared/output_format.md}

Extract structured information from the text...
```

### Tool Libraries

Group related tools for easy discovery:

```python
# tools/content/__init__.py
from .extractors import ContentExtractor, TopicExtractor
from .validators import ContentValidator, FormatChecker
from .transformers import TextCleaner, StructureConverter

__all__ = ['ContentExtractor', 'ContentValidator', 'TextCleaner']
```

## Development vs. Production Structure

### Development Layout

```
my-project/
├── dev/
│   ├── experiments/           # Prototype workflows
│   ├── testing/              # Test data and configs
│   └── sandbox/              # Quick iterations
├── src/                      # Main development
└── deploy/                   # Production configs
```

### Production Deployment

```
production/
├── config/
│   ├── prod_agent_actions.yml
│   └── environment_vars.yml
├── workflows/                # Only production workflows
├── monitoring/              # Logs and metrics
└── backups/                 # Schema and prompt backups
```

## Best Practices

### 1. **Schema-First Design**
- Define schemas before building workflows
- Use descriptive schema names
- Version schemas when making changes

### 2. **Prompt Version Control**
- Keep prompts in markdown files
- Use git for prompt versioning
- Document prompt changes and rationale

### 3. **Tool Organization**
- Group related functions in modules
- Write comprehensive docstrings
- Include unit tests for custom tools

### 4. **Workflow Naming**
- Use descriptive, consistent names
- Include complexity indicator (simple/complex)
- Version workflows when updating

### 5. **Documentation**
- README in each workflow directory
- Document dependencies between workflows
- Maintain architecture decision records

## Migration from Existing Projects

### From Scattered Scripts

1. **Identify reusable components** in existing code
2. **Extract schemas** from data structures
3. **Convert scripts** to agent workflow configs
4. **Centralize prompts** from hardcoded strings

### From Other Frameworks

1. **Map existing agents** to Agent Actions types
2. **Extract dependencies** into DAG structure
3. **Define schemas** for validation
4. **Migrate custom tools** to tools directory

---

**This production structure demonstrates how Agent Actions enables platform thinking**: shared components, multiple workflows, and organized reusability at production scale.