# Agent-Actions Example Projects

Sample workflows demonstrating Agent-Actions patterns in real-world scenarios. Each directory is a **standalone project** you can copy, configure, and run independently.

## Quick Start

```bash
# 1. Pick a project
cd examples/incident_triage

# 2. Configure credentials
cp .env.example .env
# Edit .env with your API keys

# 3. Run the workflow
agac run -a incident_triage
```

## Projects

### [incident_triage](./incident_triage)

Automated incident triage: classify severity, assess impact, assign teams, generate response plans.

| Pattern | How it's used |
|---------|---------------|
| Parallel evaluation | 3 independent severity classifiers |
| Aggregation | Weighted consensus via tool action |
| Dynamic injection | Team assignment from seed data |
| Guards | Executive summary only for SEV1/SEV2 |

---

### [automated_ml_pipeline](./automated_ml_pipeline)

End-to-end AutoML: data quality gating, feature engineering, parallel model training, champion selection, conditional deployment.

| Pattern | How it's used |
|---------|---------------|
| Quality gates | Data must score >= 0.7 to proceed |
| Parallel training | 3 algorithms trained simultaneously |
| Loop consumption | Merge evaluations for model selection |
| Conditional deployment | Deploy only if readiness >= 0.8 |

---

### [book_catalog_enrichment](./book_catalog_enrichment)

Enrich book entries with BISAC classification, marketing copy, SEO, recommendations, and quality scoring.

| Pattern | How it's used |
|---------|---------------|
| Reprompt validation | Auto-retry on invalid BISAC codes / short descriptions |
| Grounded retrieval | Search real catalog before recommending (prevents hallucination) |
| Parallel branches | SEO, recommendations, reading level run concurrently |
| Passthrough | Preserve source metadata through pipeline |

---

### [prompt_injection_detection](./prompt_injection_detection)

Multi-layer prompt injection defense: regex scanning, statistical anomaly scoring, semantic analysis, and composite risk judgment.

| Pattern | How it's used |
|---------|---------------|
| Tool + LLM pipeline | 4 statistical detectors feed into LLM interpretation |
| Guard-based routing | Different report types for BLOCK vs PASS decisions |
| Score aggregation | Composite risk from multiple detection layers |

---

### [root_cause_analysis](./root_cause_analysis)

Causal discovery for system anomalies: parallel hypothesis generation, evidence-based validation, causal chain construction, remediation planning.

| Pattern | How it's used |
|---------|---------------|
| Multi-strategy parallel | 3 reasoning strategies (data-driven, topology, pattern-matching) |
| Weighted evidence scoring | Rank hypotheses by evidence quality and consensus |
| Seed data enrichment | System topology, historical incidents, causal patterns |
| Causal chain construction | Root cause to observed symptom with mechanisms |

---

### [support_resolution](./support_resolution)

Issue-to-resolution pipeline: analyze a support ticket, research in parallel, generate customer response, internal task, and draft PR.

| Pattern | How it's used |
|---------|---------------|
| Parallel research | 3 research strategies (codebase, docs, similar issues) |
| Fan-in synthesis | Merge and deduplicate research findings |
| Multi-output | Customer response + internal task + PR draft |
| Conditional PR | Draft PR only when code change is needed |
| Batch mode | Uses Anthropic Claude (batch execution) |

---

## Project Structure

Every project follows the same layout:

```
<project>/
  agent_actions.yml          # Project-level config (model, storage, tool paths)
  .env.example               # API key template (copy to .env)
  agent_workflow/
    <workflow>/
      agent_config/
        <workflow>.yml        # Workflow definition (actions, dependencies, guards)
      seed_data/              # Reference data injected into context
      agent_io/
        staging/              # Input data goes here
        target/               # Output data lands here
      README.md               # Workflow-specific documentation
  schema/                     # Output schemas for each action
  tools/                      # Custom tool implementations (Python UDFs)
  prompt_store/               # LLM prompt templates
```

## Pattern Index

| Pattern | Example Projects |
|---------|-----------------|
| Parallel evaluation + aggregation | incident_triage, root_cause_analysis, support_resolution |
| Guards (conditional execution) | incident_triage, automated_ml_pipeline, prompt_injection_detection, support_resolution |
| Reprompt validation | book_catalog_enrichment |
| Grounded retrieval | book_catalog_enrichment |
| Dynamic content injection | incident_triage |
| Quality gates | automated_ml_pipeline |
| Passthrough (data lineage) | book_catalog_enrichment, automated_ml_pipeline, incident_triage |
| Seed data enrichment | incident_triage, root_cause_analysis |
| Batch execution | support_resolution |

## Configuration

All projects default to **OpenAI GPT-4o-mini** except `support_resolution` which uses **Anthropic Claude Sonnet**. To change the model, edit `defaults` in the workflow YAML:

```yaml
defaults:
  model_vendor: openai        # or: anthropic
  model_name: gpt-4o-mini     # or: claude-sonnet-4-20250514
  api_key: OPENAI_API_KEY     # env var name (resolved from .env)
```
