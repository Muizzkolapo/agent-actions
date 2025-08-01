# Gemini Batch Provider

This document describes how to use Google's Gemini API for batch processing in agent-actions.

## Overview

The Gemini Batch Provider allows you to process large volumes of data using Google's Gemini models through their batch API. This provides:

- **Cost savings**: Batch API offers reduced pricing compared to regular API calls
- **High throughput**: Process thousands of requests in parallel
- **Asynchronous processing**: Submit jobs and retrieve results later (within 24 hours)
- **Multiple model support**: Use various Gemini models including Flash and Pro variants

## Configuration

To use the Gemini provider, add `batch_provider: gemini` to your agent configuration:

```yaml
agents:
  - agent_type: enrichment
    name: content_enricher
    model_name: gemini-2.5-flash
    batch_provider: gemini  # Use Gemini instead of OpenAI
    run_mode: batch
    prompt: $enrich_content
    schema_name: enriched_content
```

## Installation

First, install the required Google Gemini package:

```bash
pip install google-genai
```

## Authentication

Set your Google API key as an environment variable:

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

Alternatively, you can specify it in the agent configuration:

```yaml
agents:
  - agent_type: enrichment
    google_api_key: your-api-key-here  # Not recommended for production
    batch_provider: gemini
    # ... other config
```

## Supported Models

The following Gemini models support batch processing:

- `gemini-2.5-flash` - Fast, efficient model for most tasks
- `gemini-2.5-flash-lite` - Lighter version for simpler tasks
- `gemini-2.5-pro` - More capable model for complex tasks
- `gemini-2.0-flash` - Previous generation flash model
- `gemini-2.0-flash-preview-image-generation` - For generating images

## Usage Example

### 1. Create your agent configuration

```yaml
workflow: data_enrichment
agents:
  - agent_type: analyzer
    name: gemini_analyzer
    model_name: gemini-2.5-flash
    batch_provider: gemini
    run_mode: batch
    prompt: |
      Analyze the following data and extract key insights:
      {content}
    schema_name: analysis_results
    temperature: 0.1
```

### 2. Run the workflow

```bash
agent-actions run data_enrichment
```

### 3. Process completed batches

```bash
agent-actions batch --batch_continue data_enrichment
```

## Key Differences from OpenAI

1. **Request Format**: Gemini uses a different JSON structure with `key` instead of `custom_id`
2. **Response Format**: Results are nested differently in the response structure
3. **Schema Support**: Gemini doesn't currently support native schema validation (schemas are included in the prompt)
4. **File Upload**: Uses Google's Files API instead of OpenAI's file system

## Limitations

- No native structured output support (yet) - schemas are enforced through prompting
- 24-hour processing window
- File size limits apply to batch input files

## Migration from OpenAI

To migrate existing workflows from OpenAI to Gemini:

1. Add `batch_provider: gemini` to your agent configuration
2. Update `model_name` to a supported Gemini model
3. Ensure your prompts work well with Gemini (they're generally compatible)
4. Set up Google API authentication

The rest of your workflow remains unchanged - the provider abstraction handles all format differences transparently.

## Monitoring Batch Jobs

The batch registry (`.batch_registry.json`) tracks all submitted jobs including the provider used. You can check the status of Gemini batch jobs the same way as OpenAI jobs:

```bash
agent-actions batch --batch_status
```

## Troubleshooting

### Missing Dependency Error
If you see `Gemini provider not available: google-genai package is not installed`, install the package:
```bash
pip install google-genai
```

### Authentication Errors
- Ensure `GOOGLE_API_KEY` is set correctly
- Check that your API key has access to the Gemini API

### Model Not Supported
- Verify you're using a model from the supported list above
- Check for typos in the model name

### Batch Job Failures
- Check the error messages in the batch results
- Ensure your input data is properly formatted
- Verify that your prompts are generating valid responses

## Example: Multi-Provider Workflow

You can use different providers for different agents in the same workflow:

```yaml
workflow: multi_provider_pipeline
agents:
  - agent_type: classifier
    model_name: gpt-4o-mini
    batch_provider: openai  # Use OpenAI for classification
    run_mode: batch
    
  - agent_type: enrichment
    model_name: gemini-2.5-flash
    batch_provider: gemini  # Use Gemini for enrichment
    run_mode: batch
    dependencies: [classifier]
```

This allows you to leverage the strengths of each provider where they excel.