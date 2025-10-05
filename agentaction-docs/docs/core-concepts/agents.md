---
title: Agents
description: Understanding agents as transformation nodes in DAG workflows
sidebar_position: 1
---

# Agents

Agents in Agent Actions are **deterministic transformation nodes** that convert inputs into structured, validated outputs. Unlike autonomous agents that make decisions and take actions, Agent Actions agents are pure functions focused on data transformation within DAG workflows.

## What Are Agents?

### Transformation Nodes
Agents are specialized processing units that:

- **Receive Input**: Structured data from previous agents or workflow input
- **Transform Data**: Use LLM capabilities to process and modify data
- **Produce Output**: Generate structured JSON conforming to schemas
- **Maintain State**: Are completely stateless between executions

### Key Characteristics

- **Deterministic**: Same inputs always produce the same outputs
- **Schema-Bound**: All outputs must conform to predefined JSON schemas
- **Dependency-Aware**: Explicitly declare required inputs from other agents
- **Model-Agnostic**: Work with any supported AI model provider

## Agent Configuration

### Basic Agent Structure

```yaml
agents:
  - name: "text_analyzer"
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: |
      Analyze the provided text and extract key information.

      Text: {input_text}

      Provide structured output with sentiment, entities, and summary.

    output_schema: "analysis_schema"
    depends_on: []
```

### Configuration Properties

| Property | Required | Description |
|----------|----------|-------------|
| `name` | Yes | Unique identifier for the agent |
| `model_vendor` | Yes | AI provider (openai, anthropic, etc.) |
| `model_name` | Yes | Specific model to use |
| `prompt` | Yes | Template for LLM instructions |
| `output_schema` | Yes | JSON schema for output validation |
| `depends_on` | Yes | List of required predecessor agents |

## Agent Dependencies

### Dependency Declaration

Dependencies are explicitly declared and determine execution order:

```yaml
agents:
  # Root agent - no dependencies
  - name: "data_extractor"
    depends_on: []

  # Depends on data_extractor
  - name: "sentiment_analyzer"
    depends_on: ["data_extractor"]

  # Depends on data_extractor
  - name: "entity_extractor"
    depends_on: ["data_extractor"]

  # Depends on both analyzers
  - name: "report_generator"
    depends_on: ["sentiment_analyzer", "entity_extractor"]
```

### Data Access in Prompts

Agent Actions uses `{reference.field}` syntax to access data in prompts. You can reference:

- **Source data**: `{source.field}` - Original workflow input
- **Agent outputs**: `{agent_name.field}` - Outputs from dependency agents
- **Loop context**: `{loop.index}`, `{loop.item.field}` - Loop iteration data
- **Workflow metadata**: `{workflow.name}`, `{workflow.version}` - Workflow info

#### Accessing Source Data

Reference original workflow input using `{source.field}`:

```yaml
agents:
  - name: "document_analyzer"
    prompt: |
      Analyze this document:

      Title: {source.title}
      Content: {source.page_content}
      Author: {source.metadata.author}
    depends_on: []
```

#### Accessing Dependency Outputs

Access outputs from agents listed in `depends_on`:

```yaml
agents:
  - name: "content_writer"
    prompt: |
      Write compelling content based on the analysis:

      Sentiment: {sentiment_analyzer.sentiment}
      Key Entities: {entity_extractor.entities}
      Summary: {data_extractor.summary}

      Create engaging marketing copy.
    depends_on: ["sentiment_analyzer", "entity_extractor", "data_extractor"]
```

#### Nested Field Access

Navigate nested structures with dot notation:

```yaml
prompt: |
  Report accuracy: {analyzer.results.metrics.accuracy}
  First item: {extractor.items.0}
```

:::tip
See [Field Referencing](/core-concepts/field-referencing) for complete documentation on all reference types and patterns.
:::

## Model Configuration

### Supported Providers

Agent Actions supports multiple AI providers:

```yaml
# OpenAI
- name: "openai_agent"
  model_vendor: "openai"
  model_name: "gpt-4"

# Anthropic
- name: "anthropic_agent"
  model_vendor: "anthropic"
  model_name: "claude-3-sonnet-20240229"

# Google
- name: "google_agent"
  model_vendor: "google"
  model_name: "gemini-pro"

# Local/Ollama
- name: "local_agent"
  model_vendor: "ollama"
  model_name: "llama2"
```

### Model-Specific Parameters

Configure model behavior with additional parameters:

```yaml
agents:
  - name: "creative_writer"
    model_vendor: "openai"
    model_name: "gpt-4"
    model_config:
      temperature: 0.8      # Higher creativity
      max_tokens: 1000      # Longer responses
      top_p: 0.9           # Nucleus sampling
    prompt: "Write creative content..."
```

## Prompt Engineering

### Template Variables

Use template variables to access data:

```yaml
agents:
  - name: "personalizer"
    prompt: |
      Personalize this content for the user:

      Original Content: {base_content}
      User Profile: {user_analyzer.profile}
      Preferences: {user_analyzer.preferences}

      Create personalized version maintaining the core message.
    depends_on: ["user_analyzer"]
```

### Conditional Logic

Include conditional logic in prompts:

```yaml
agents:
  - name: "adaptive_responder"
    prompt: |
      {% if sentiment_analyzer.sentiment == "negative" %}
      Address the negative sentiment with empathy and solutions:
      {% elif sentiment_analyzer.sentiment == "positive" %}
      Amplify the positive sentiment with enthusiasm:
      {% else %}
      Provide balanced, informative response:
      {% endif %}

      User Input: {user_input}
      Detected Sentiment: {sentiment_analyzer.sentiment}
```

## Agent Patterns

### Data Enrichment

Progressively enrich data through multiple agents:

```yaml
agents:
  # Stage 1: Basic extraction
  - name: "basic_extractor"
    prompt: "Extract basic information: {raw_data}"
    output_schema: "basic_info"
    depends_on: []

  # Stage 2: Add analysis
  - name: "analyzer"
    prompt: "Analyze the extracted info: {basic_extractor.output}"
    output_schema: "analyzed_info"
    depends_on: ["basic_extractor"]

  # Stage 3: Generate insights
  - name: "insight_generator"
    prompt: "Generate insights from: {analyzer.output}"
    output_schema: "insights"
    depends_on: ["analyzer"]
```

### Parallel Processing

Process different aspects simultaneously:

```yaml
agents:
  # Common input processor
  - name: "input_processor"
    depends_on: []

  # Parallel analyzers
  - name: "sentiment_analysis"
    depends_on: ["input_processor"]

  - name: "topic_analysis"
    depends_on: ["input_processor"]

  - name: "style_analysis"
    depends_on: ["input_processor"]

  # Combine results
  - name: "comprehensive_report"
    prompt: |
      Create comprehensive report combining:
      Sentiment: {sentiment_analysis.output}
      Topics: {topic_analysis.output}
      Style: {style_analysis.output}
    depends_on: ["sentiment_analysis", "topic_analysis", "style_analysis"]
```

### Validation Chain

Implement quality assurance through validation agents:

```yaml
agents:
  - name: "content_generator"
    depends_on: []

  - name: "quality_validator"
    prompt: |
      Validate the generated content:
      Content: {content_generator.output}

      Check for accuracy, completeness, and adherence to guidelines.
    depends_on: ["content_generator"]

  - name: "final_formatter"
    prompt: |
      Format the validated content:
      Content: {content_generator.output}
      Validation: {quality_validator.output}
    depends_on: ["content_generator", "quality_validator"]
```

## Error Handling

### Schema Validation Failures

When an agent's output doesn't match its schema:

1. **Execution Stops**: The workflow halts at the failing agent
2. **Error Details**: Specific validation errors are reported
3. **Manual Review**: Requires fixing the prompt or schema
4. **Retry**: Re-run the workflow after fixes

### Dependency Management

Missing dependencies are caught during workflow validation:

```yaml
# This will fail - unknown_agent doesn't exist
agents:
  - name: "dependent_agent"
    depends_on: ["unknown_agent"]  # ERROR: dependency not found
```

## Best Practices

### 1. Clear Naming
Use descriptive, consistent agent names:

```yaml
# Good
- name: "product_sentiment_analyzer"
- name: "customer_review_summarizer"

# Poor
- name: "agent1"
- name: "processor"
```

### 2. Focused Responsibility
Each agent should have a single, clear purpose:

```yaml
# Good - focused agents
- name: "extract_entities"
- name: "analyze_sentiment"
- name: "generate_summary"

# Poor - multi-purpose agent
- name: "do_everything"
```

### 3. Explicit Dependencies
Be explicit about what each agent needs:

```yaml
# Good - clear dependencies
- name: "report_writer"
  depends_on: ["data_analyzer", "trend_calculator"]

# Poor - unnecessary dependencies
- name: "simple_formatter"
  depends_on: ["everything", "just_in_case"]
```

### 4. Schema Design
Design schemas that match your agent's purpose:

```json
{
  "type": "object",
  "properties": {
    "primary_result": {"type": "string"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "metadata": {
      "type": "object",
      "properties": {
        "processing_time": {"type": "number"},
        "model_used": {"type": "string"}
      }
    }
  },
  "required": ["primary_result", "confidence"]
}
```

## Next Steps

- **[Workflow Design](./workflows.md)** - Learn to orchestrate agents in DAGs
- **[Schema Validation](./schemas.md)** - Master JSON schema design
- **[Reprompting & Validators](../guides/reprompting.md)** - Validate outputs and retry with improved prompts
- **Examples** (coming soon) - See real-world agent patterns