---
title: Schema Validation
description: Master JSON schema design for structured AI outputs
sidebar_position: 3
---

# Schema Validation

Schema validation is the cornerstone of Agent Actions' **deterministic approach**. Every agent output must conform to a predefined JSON schema, ensuring structured, predictable, and type-safe results throughout your DAG workflows.

## Why Schema-First?

### Eliminates AI Unpredictability
AI models can be inconsistent in their output format. Schemas enforce structure:

- **Consistent Format**: Same structure every time
- **Type Safety**: Guaranteed data types
- **Required Fields**: Never miss critical information
- **Validation Errors**: Clear feedback when outputs don't conform

### Enables Reliable Workflows
Schema validation makes DAG workflows robust:

- **Predictable Inputs**: Dependent agents receive expected data structures
- **Error Prevention**: Catch format issues before they propagate
- **Documentation**: Schemas serve as API contracts between agents
- **Testing**: Validate agent behavior with expected outputs

## JSON Schema Basics

### Schema Structure
Agent Actions uses JSON Schema Draft 7:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "field_name": {
      "type": "string",
      "description": "Human-readable description"
    }
  },
  "required": ["field_name"],
  "additionalProperties": false
}
```

### Basic Types

```json
{
  "type": "object",
  "properties": {
    "text_field": {"type": "string"},
    "number_field": {"type": "number"},
    "integer_field": {"type": "integer"},
    "boolean_field": {"type": "boolean"},
    "array_field": {"type": "array"},
    "object_field": {"type": "object"},
    "null_field": {"type": "null"}
  }
}
```

### String Constraints

```json
{
  "type": "object",
  "properties": {
    "short_text": {
      "type": "string",
      "maxLength": 100,
      "minLength": 1
    },
    "email": {
      "type": "string",
      "format": "email"
    },
    "category": {
      "type": "string",
      "enum": ["news", "blog", "academic", "social"]
    },
    "product_code": {
      "type": "string",
      "pattern": "^[A-Z]{2}[0-9]{4}$"
    }
  }
}
```

### Numeric Constraints

```json
{
  "type": "object",
  "properties": {
    "confidence_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Confidence level between 0 and 1"
    },
    "rating": {
      "type": "integer",
      "minimum": 1,
      "maximum": 5
    },
    "price": {
      "type": "number",
      "multipleOf": 0.01,
      "minimum": 0
    }
  }
}
```

### Array Constraints

```json
{
  "type": "object",
  "properties": {
    "keywords": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 1,
      "maxItems": 10,
      "uniqueItems": true
    },
    "coordinates": {
      "type": "array",
      "items": {"type": "number"},
      "minItems": 2,
      "maxItems": 2
    },
    "categories": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["tech", "business", "health", "education"]
      }
    }
  }
}
```

## Array-Type Root Schemas

Agent Actions supports array-type schemas at the root level, allowing you to define schemas where the response is directly an array:

```yaml
name: candidate_facts_list
description: "List of candidate facts extracted from content"
type: array
items:
  type: object
  properties:
    fact:
      type: string
      description: "A testable fact"
      maxLength: 250
    source:
      type: string
      description: "Source of the fact"
    confidence:
      type: string
      description: "Confidence level"
  required:
    - fact
    - source
```

This format is automatically converted to the unified format internally and works with all providers (OpenAI, Anthropic, Gemini, Ollama).

The array will be wrapped in an object with a property matching the schema name in the API response:

```json
{
  "candidate_facts_list": [
    {
      "fact": "GitHub Actions supports matrix builds",
      "source": "GitHub documentation",
      "confidence": "high"
    },
    {
      "fact": "Workflows can be triggered by 20+ event types",
      "source": "GitHub API reference",
      "confidence": "high"
    }
  ]
}
```

### Primitive Array Schemas

You can also define arrays of primitive types:

```yaml
name: tags
type: array
items:
  type: string
```

This will result in:

```json
{
  "tags": ["python", "automation", "ci-cd"]
}
```

## Schema Design Patterns

### Basic Analysis Result

```json
{
  "type": "object",
  "properties": {
    "summary": {
      "type": "string",
      "maxLength": 500,
      "description": "Brief summary of the analysis"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Confidence level of the analysis"
    },
    "categories": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 1,
      "description": "Identified categories"
    },
    "metadata": {
      "type": "object",
      "properties": {
        "processing_time": {"type": "number"},
        "model_version": {"type": "string"}
      }
    }
  },
  "required": ["summary", "confidence", "categories"]
}
```

### Sentiment Analysis Schema

```json
{
  "type": "object",
  "properties": {
    "sentiment": {
      "type": "string",
      "enum": ["positive", "negative", "neutral"],
      "description": "Overall sentiment classification"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "scores": {
      "type": "object",
      "properties": {
        "positive": {"type": "number", "minimum": 0, "maximum": 1},
        "negative": {"type": "number", "minimum": 0, "maximum": 1},
        "neutral": {"type": "number", "minimum": 0, "maximum": 1}
      },
      "required": ["positive", "negative", "neutral"]
    },
    "aspects": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "aspect": {"type": "string"},
          "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
          "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["aspect", "sentiment", "confidence"]
      }
    }
  },
  "required": ["sentiment", "confidence", "scores"]
}
```

### Entity Extraction Schema

```json
{
  "type": "object",
  "properties": {
    "entities": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "text": {"type": "string"},
          "type": {
            "type": "string",
            "enum": ["PERSON", "ORGANIZATION", "LOCATION", "DATE", "MONEY", "PRODUCT"]
          },
          "confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "start_pos": {"type": "integer", "minimum": 0},
          "end_pos": {"type": "integer", "minimum": 0}
        },
        "required": ["text", "type", "confidence"]
      },
      "description": "Extracted named entities"
    },
    "entity_counts": {
      "type": "object",
      "properties": {
        "PERSON": {"type": "integer", "minimum": 0},
        "ORGANIZATION": {"type": "integer", "minimum": 0},
        "LOCATION": {"type": "integer", "minimum": 0}
      }
    }
  },
  "required": ["entities"]
}
```

### Content Generation Schema

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "maxLength": 100,
      "minLength": 10
    },
    "content": {
      "type": "string",
      "maxLength": 2000,
      "minLength": 50
    },
    "keywords": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 3,
      "maxItems": 10
    },
    "word_count": {
      "type": "integer",
      "minimum": 10
    },
    "reading_time": {
      "type": "number",
      "minimum": 0.1,
      "description": "Estimated reading time in minutes"
    },
    "style": {
      "type": "string",
      "enum": ["formal", "casual", "technical", "creative"]
    }
  },
  "required": ["title", "content", "keywords", "word_count"]
}
```

## Advanced Schema Features

### Conditional Schemas

Use `if/then/else` for conditional validation:

```json
{
  "type": "object",
  "properties": {
    "content_type": {"type": "string", "enum": ["article", "summary"]},
    "content": {"type": "string"},
    "word_count": {"type": "integer"}
  },
  "if": {
    "properties": {"content_type": {"const": "article"}}
  },
  "then": {
    "properties": {
      "word_count": {"minimum": 500}
    }
  },
  "else": {
    "properties": {
      "word_count": {"maximum": 200}
    }
  }
}
```

### Schema Composition

Reuse schema components with `$ref`:

```json
{
  "definitions": {
    "confidence_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    },
    "entity": {
      "type": "object",
      "properties": {
        "text": {"type": "string"},
        "type": {"type": "string"},
        "confidence": {"$ref": "#/definitions/confidence_score"}
      }
    }
  },
  "type": "object",
  "properties": {
    "overall_confidence": {"$ref": "#/definitions/confidence_score"},
    "entities": {
      "type": "array",
      "items": {"$ref": "#/definitions/entity"}
    }
  }
}
```

### Nested Objects

Structure complex hierarchical data:

```json
{
  "type": "object",
  "properties": {
    "document_analysis": {
      "type": "object",
      "properties": {
        "structure": {
          "type": "object",
          "properties": {
            "sections": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "title": {"type": "string"},
                  "content": {"type": "string"},
                  "subsections": {
                    "type": "array",
                    "items": {
                      "type": "object",
                      "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"}
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

## Schema Evolution Patterns

### Progressive Enrichment

Design schemas that build upon each other:

```json
// Stage 1: Basic extraction
{
  "type": "object",
  "properties": {
    "raw_text": {"type": "string"},
    "detected_language": {"type": "string"}
  },
  "required": ["raw_text"]
}

// Stage 2: Analysis added
{
  "type": "object",
  "properties": {
    "raw_text": {"type": "string"},
    "detected_language": {"type": "string"},
    "sentiment": {"type": "string"},
    "entities": {"type": "array"},
    "topics": {"type": "array"}
  },
  "required": ["raw_text", "sentiment"]
}

// Stage 3: Insights generated
{
  "type": "object",
  "properties": {
    "raw_text": {"type": "string"},
    "detected_language": {"type": "string"},
    "sentiment": {"type": "string"},
    "entities": {"type": "array"},
    "topics": {"type": "array"},
    "insights": {"type": "array"},
    "recommendations": {"type": "array"}
  },
  "required": ["raw_text", "sentiment", "insights"]
}
```

### Modular Schema Design

Create reusable schema modules:

```json
// schemas/common/confidence.json
{
  "type": "number",
  "minimum": 0,
  "maximum": 1,
  "description": "Confidence score between 0 and 1"
}

// schemas/common/entity.json
{
  "type": "object",
  "properties": {
    "text": {"type": "string"},
    "type": {"type": "string"},
    "confidence": {"$ref": "confidence.json"}
  },
  "required": ["text", "type", "confidence"]
}

// schemas/analysis_result.json
{
  "type": "object",
  "properties": {
    "overall_confidence": {"$ref": "common/confidence.json"},
    "entities": {
      "type": "array",
      "items": {"$ref": "common/entity.json"}
    }
  }
}
```

## Validation Error Handling

### Common Validation Errors

Understanding typical schema validation failures:

```javascript
// Type mismatch
{
  "error": "Expected string, got number",
  "path": "/summary",
  "value": 123
}

// Missing required field
{
  "error": "Missing required property",
  "path": "/confidence",
  "schema": {"required": ["confidence"]}
}

// Constraint violation
{
  "error": "String too long",
  "path": "/title",
  "constraint": "maxLength: 100",
  "actual_length": 150
}

// Enum violation
{
  "error": "Value not in allowed list",
  "path": "/sentiment",
  "allowed": ["positive", "negative", "neutral"],
  "actual": "happy"
}
```

### Schema Debugging

Tips for debugging schema validation issues:

1. **Start Simple**: Begin with basic schemas and add constraints gradually
2. **Use Examples**: Include example outputs in schema documentation
3. **Test Incrementally**: Validate against known good outputs
4. **Clear Error Messages**: Use descriptive field names and descriptions

### Schema Validation in Prompts

Guide AI models to produce valid outputs:

```yaml
agents:
  - name: "structured_analyzer"
    prompt: |
      Analyze the text and provide output in this EXACT JSON format:

      {
        "sentiment": "positive|negative|neutral",
        "confidence": 0.85,
        "summary": "Brief summary under 200 characters",
        "keywords": ["keyword1", "keyword2", "keyword3"]
      }

      Important:
      - sentiment must be exactly one of: positive, negative, neutral
      - confidence must be a number between 0 and 1
      - summary must be under 200 characters
      - keywords must be an array of 3-5 strings

      Text to analyze: {input_text}
    output_schema: "analysis_schema"
```

## Best Practices

### 1. Design for Clarity
Make schemas self-documenting:

```json
{
  "type": "object",
  "description": "Product review sentiment analysis result",
  "properties": {
    "overall_sentiment": {
      "type": "string",
      "enum": ["positive", "negative", "neutral"],
      "description": "Overall sentiment classification of the review"
    },
    "confidence_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Model confidence in the sentiment classification (0-1)"
    }
  }
}
```

### 2. Use Appropriate Constraints
Set realistic bounds:

```json
{
  "properties": {
    "summary": {
      "type": "string",
      "minLength": 50,    // Ensure meaningful content
      "maxLength": 500    // Prevent overly long output
    },
    "rating": {
      "type": "integer",
      "minimum": 1,       // Meaningful minimum
      "maximum": 5        // Standard rating scale
    }
  }
}
```

### 3. Plan for Evolution
Design schemas that can grow:

```json
{
  "type": "object",
  "properties": {
    "version": {"type": "string", "const": "1.0"},
    "analysis": {"type": "object"},
    "metadata": {
      "type": "object",
      "description": "Extensible metadata object for future fields"
    }
  },
  "additionalProperties": false
}
```

### 4. Validate Early and Often
Test schemas during development:

```bash
# Test schema against sample outputs
agent-actions validate-schema analysis_schema.json sample_output.json
```

## Schema Organization

### File Structure
Organize schemas logically:

```
schemas/
├── common/
│   ├── confidence.json
│   ├── entity.json
│   └── metadata.json
├── analysis/
│   ├── sentiment.json
│   ├── entity_extraction.json
│   └── topic_classification.json
├── generation/
│   ├── content.json
│   └── summary.json
└── workflow_outputs/
    ├── document_analysis.json
    └── content_pipeline.json
```

### Schema Naming
Use consistent naming conventions:

```
// Good naming
schemas/sentiment_analysis_result.json
schemas/entity_extraction_output.json
schemas/content_generation_response.json

// Poor naming
schemas/schema1.json
schemas/output.json
schemas/result.json
```

## Next Steps

- **Examples** (coming soon) - Real-world schema implementations
- **Schema Library** (coming soon) - Pre-built schemas for common tasks
- **Advanced Validation** (coming soon) - Custom validation patterns