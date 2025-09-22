---
title: Getting Started
description: Create your first YAML-based DAG workflow
sidebar_position: 3
---

# Getting Started

This guide walks you through creating your first Agent Actions workflow using YAML-based DAG configuration with schema validation.

## Your First DAG Workflow

Let's create a multi-agent workflow that processes product data through a structured pipeline.

### 1. Define Your Schemas

First, create JSON schemas for structured output validation:

**`schemas/product_data.json`**:
```json
{
  "type": "object",
  "properties": {
    "product_name": {"type": "string"},
    "category": {"type": "string"},
    "key_features": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 3
    },
    "extracted_specs": {
      "type": "object",
      "properties": {
        "price_range": {"type": "string"},
        "target_audience": {"type": "string"}
      },
      "required": ["price_range", "target_audience"]
    }
  },
  "required": ["product_name", "category", "key_features", "extracted_specs"]
}
```

**`schemas/marketing_content.json`**:
```json
{
  "type": "object",
  "properties": {
    "headline": {"type": "string", "maxLength": 60},
    "description": {"type": "string", "maxLength": 200},
    "key_benefits": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 3,
      "maxItems": 5
    },
    "target_keywords": {
      "type": "array",
      "items": {"type": "string"}
    }
  },
  "required": ["headline", "description", "key_benefits"]
}
```

### 2. Create Your Workflow Configuration

Create `product_workflow.yaml`:

```yaml
# Product processing DAG workflow
workflow_name: "product_content_pipeline"
description: "Extract product data and generate marketing content"

# Schema definitions
schemas:
  product_data: "./schemas/product_data.json"
  marketing_content: "./schemas/marketing_content.json"

# Agent definitions
agents:
  - name: "data_extractor"
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: |
      Extract structured product information from the provided text.
      Focus on: product name, category, key features, pricing, and target audience.

      Input: {input_text}

    output_schema: "product_data"
    depends_on: []

  - name: "content_generator"
    model_vendor: "openai"
    model_name: "gpt-4"
    prompt: |
      Create compelling marketing content based on the product data.
      Generate a catchy headline, engaging description, and key benefits.

      Product Data: {data_extractor.output}

    output_schema: "marketing_content"
    depends_on: ["data_extractor"]

# Workflow execution
workflow:
  input_data:
    input_text: |
      Smart Fitness Tracker Pro - Advanced health monitoring device
      with heart rate tracking, sleep analysis, and GPS functionality.
      Price: $199-249. Perfect for fitness enthusiasts and health-conscious users.

  agents: ["data_extractor", "content_generator"]
```

### 3. Run Your DAG Workflow

```bash
agent-actions run product_workflow.yaml
```

The workflow will:
1. **Extract Data**: Parse product information into validated JSON structure
2. **Generate Content**: Create marketing materials based on extracted data
3. **Validate Outputs**: Ensure all outputs conform to their JSON schemas
4. **Return Results**: Provide structured, validated results

### 4. Understanding the Output

You'll see deterministic output like:

```
🔄 Executing DAG: product_content_pipeline
├── ✅ data_extractor (completed)
│   └── Output: {"product_name": "Smart Fitness Tracker Pro", ...}
├── ✅ content_generator (completed)
│   └── Output: {"headline": "Track Your Fitness Like a Pro", ...}
└── ✅ Workflow completed successfully

📊 Results:
{
  "data_extractor": {
    "product_name": "Smart Fitness Tracker Pro",
    "category": "Wearable Technology",
    "key_features": ["Heart Rate Tracking", "Sleep Analysis", "GPS"],
    "extracted_specs": {
      "price_range": "$199-249",
      "target_audience": "Fitness enthusiasts and health-conscious users"
    }
  },
  "content_generator": {
    "headline": "Track Your Fitness Like a Pro",
    "description": "Advanced health monitoring with precision tracking...",
    "key_benefits": ["24/7 Health Monitoring", "GPS Accuracy", "Sleep Insights"]
  }
}
```

## Key Concepts Explained

### DAG (Directed Acyclic Graph)
Workflows are structured as DAGs where:
- **Nodes** are agents (transformation units)
- **Edges** represent data dependencies
- **Execution order** is determined by dependencies
- **No cycles** ensures predictable execution

### Agents as Transformation Nodes
Each agent is a pure transformation function:
- **Input**: Data from previous agents or workflow input
- **Processing**: LLM-based transformation with a specific prompt
- **Output**: Structured JSON validated against a schema
- **Dependencies**: Explicit list of required preceding agents

### Schema-First Validation
Every agent output must conform to a JSON schema:
- **Structure enforcement**: Guarantees consistent output format
- **Type validation**: Ensures data types match expectations
- **Required fields**: Prevents missing critical information
- **Constraints**: Min/max values, string lengths, array sizes

### Deterministic Execution
Unlike autonomous agents, Agent Actions provides predictable results:
- **Same inputs** always produce the same outputs
- **No hidden state** or memory between runs
- **Fixed dependencies** prevent execution order variations
- **Schema validation** eliminates output unpredictability

## Next Steps

Now that you've created your first DAG workflow, explore:

1. **[Core Concepts](./core-concepts/)** - Deep dive into DAG architecture
2. **[Agents Guide](./core-concepts/agents.md)** - Master agent configuration
3. **[Workflow Design](./core-concepts/workflows.md)** - Learn DAG patterns
4. **[Schema Validation](./core-concepts/schemas.md)** - Schema design best practices

## Common DAG Patterns

### Sequential Processing Pipeline
```yaml
# Linear data transformation chain
agents:
  - name: "extract"
    depends_on: []
  - name: "transform"
    depends_on: ["extract"]
  - name: "validate"
    depends_on: ["transform"]
```

### Parallel Processing with Merge
```yaml
# Process data in parallel, then combine
agents:
  - name: "analyze_sentiment"
    depends_on: ["input_processor"]
  - name: "extract_entities"
    depends_on: ["input_processor"]
  - name: "generate_summary"
    depends_on: ["analyze_sentiment", "extract_entities"]
```

### Complex Multi-Branch DAG
```yaml
# Sophisticated workflow with multiple paths
agents:
  - name: "data_ingestion"
    depends_on: []
  - name: "quality_check"
    depends_on: ["data_ingestion"]
  - name: "content_analysis"
    depends_on: ["quality_check"]
  - name: "metadata_extraction"
    depends_on: ["quality_check"]
  - name: "final_report"
    depends_on: ["content_analysis", "metadata_extraction"]
```

### Schema Evolution Pattern
```yaml
# Progressive data enrichment through the pipeline
schemas:
  raw_data: "./schemas/raw.json"           # Simple input structure
  enriched_data: "./schemas/enriched.json" # Added analysis fields
  final_output: "./schemas/final.json"     # Complete result structure

agents:
  - name: "enricher"
    output_schema: "enriched_data"
  - name: "finalizer"
    output_schema: "final_output"
```

Ready to master DAG-based AI workflows? Continue with [Core Concepts](./core-concepts/) to understand the full power of Agent Actions.