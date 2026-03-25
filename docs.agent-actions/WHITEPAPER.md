# Agent Actions: Declarative Framework for Agentic LLM Workflows

**By Muizz Kolapo**

---

## Executive Summary

Agent Actions is a declarative context engineering framework for orchestrating multi-step agentic LLM workflows. It grew out of a need to generate LLM outputs that are properly gated and semantically consistent at scale. Agent Actions fills the gap between prototype LLM scripts and production-grade data pipelines.

Every action is a self-contained, configurable AI unit with its own model, context window, schema, and pre-check gate, running as a batch pipeline over your data. The framework controls *what each LLM step thinks about*, not just what it connects to. Context engineering means ensuring every LLM call receives the right information, from the right model, at the right cost, with the right validation. Declared in configuration, not buried in code.

The framework started from a simple observation: building reliable LLM workflows means solving the same problems over and over. Dependency management, output validation, error handling, batch processing, multi-vendor support. Rather than embedding this logic in application code, Agent Actions pulls it out into configuration, producing auditable, version-controlled pipelines that separate orchestration from business logic.

This whitepaper explains the design decisions, architectural choices, and patterns that make the framework work.

---

## The Problem: LLM Workflows at Scale

### The Prototype-to-Production Gap

Most LLM applications begin as Python scripts. A developer writes a prompt, calls an API, parses the response, and moves on. This works for prototypes and small-scale experiments. Problems emerge at scale:

**1. Reliability**
LLMs produce unpredictable outputs. A prompt that works 95% of the time fails 5% of the time—acceptable for a demo, unacceptable when processing 10,000 records. Teams need validation, retry logic, and graceful degradation.

**2. Maintainability**
As workflows grow, prompts scatter across codebases. A single workflow might involve 15 prompts across 8 files. Changing one prompt requires tracing dependencies, understanding data flow, and regression testing. Code review becomes archaeology.

**3. Observability**
When a production workflow fails at 3 AM, teams need answers: Which record failed? Which action? What was the input? What did the LLM return? Prototype scripts rarely capture this metadata.

**4. Cost Control**
LLM calls are expensive. Batch APIs offer 50% cost savings but require different integration patterns. Most prototype code is synchronous—retrofitting batch support means rewriting core logic.

**5. Vendor Lock-in**
Today's best model is tomorrow's legacy system. Teams building on a single vendor's API face migration costs when better options emerge. Abstraction layers add complexity.

### Existing Solutions Fall Short

The market offers tools, but each has limitations:

**Python-first frameworks**: Extensive abstractions that can obscure what's actually happening. Debugging requires understanding framework internals. Configuration lives in Python code, making non-developer review difficult.

**Visual workflow tools**: Designed for general automation, not purpose-built for LLM pipelines. No context isolation, no pre-check gates, no batch API support.

**Custom Solutions**: Many teams build internal tools. This works but requires ongoing maintenance, and lessons learned don't transfer between organizations.

The gap: a framework purpose-built for LLM data pipelines—declarative enough for auditing, opinionated enough to solve common problems, flexible enough for real-world complexity.

---

## The Solution: Context Engineering

Agent Actions controls **what each LLM step thinks about**. Every action is a self-contained AI unit with its own model, context window, schema, and pre-check gate. The framework orchestrates not just the *sequence* of operations, but the *information environment* of each one.

That's the difference between an LLM pipeline that works and one that works *well*.

### Transparent Decision Pathways

When multiple AI engineers build agent workflows independently, every workflow becomes a black box. Engineer A chains prompts in a Python script. Engineer B builds a visual graph. Engineer C writes raw API calls. Each approach works in isolation, but nobody can look at someone else's workflow and understand how data was generated. There is no shared vocabulary, no uniform structure, no way to audit the decision pathways that produced a given output.

Agent Actions enforces a single declarative format where every decision is visible: what data each step receives, what it produces, how validation failures are handled, and where records are filtered. Anyone on the team, including non-engineers, can open a workflow YAML and trace exactly how a piece of output was generated.

Consider the book catalog enrichment pipeline. An 11-step workflow that classifies books, writes marketing copy, generates SEO metadata, retrieves real recommendations, scores quality, and builds user-specific views. In code, this would be an opaque chain of function calls. In Agent Actions, every decision pathway is readable:

```yaml
- name: classify_genre
  schema: classify_genre                    # What it must produce
  prompt: $book_catalog_enrichment.Classify_Book_Genre  # How it decides
  context_scope:
    observe: [source.*]                     # What data it sees
  reprompt:
    validation: check_valid_bisac           # What happens if output is wrong
    max_attempts: 3                         # How many chances it gets
    on_exhausted: return_last               # What happens if it keeps failing
```

Every line is a decision. A reviewer can look at this and know: this action sees source data, must output valid BISAC codes, gets 3 attempts to self-correct, and accepts the best attempt if all fail. No Python to read. No framework internals to understand. The decision pathways are the configuration.

### Problems This Solves Structurally

This transparency compounds across the pipeline. Three problems that stay invisible in code-based approaches get solved structurally:

**Context Leak.** In a naive pipeline, every action sees everything—wasting tokens, polluting prompts with irrelevant data, and risking exposure of sensitive fields. Agent Actions eliminates this with `context_scope`, where each action declares exactly what it observes, what passes through untouched, and what gets excluded entirely (see *Core Capabilities > Context Scoping*).

**Progressive Data Exposure.** In most frameworks, each step accumulates context from all previous steps. By step 8, the LLM receives output from steps 1 through 7 whether it needs it or not. Agent Actions enforces explicit data flow—each action declares precisely which upstream fields it needs.

**Invisible Error Handling.** When an LLM produces invalid output, what happens next? In code, the answer is buried in exception handlers. In Agent Actions, every failure pathway is declared in the same YAML that defines the happy path—reprompt logic, quality gates, and static analysis errors are all visible in configuration. Broken references are caught before any LLM call:

```text
❌ write_description references 'validate_bisac.title'
   → Field 'title' not in validate_bisac schema
   → validate_bisac outputs: bisac_codes, bisac_names, bisac_valid, validation_notes
```

No hidden error handling. No implicit retry logic. No silent data loss.

### Six Capabilities at a Glance

1. **Every action picks its own model.** Step 1 uses `gpt-4o-mini` for extraction. Step 4 uses `claude-sonnet` for reasoning. Step 2 uses Gemini for cheap parallel scoring. Model selection is a **per-step cost/quality decision**.

2. **Guards are pre-check gates.** Before the LLM even runs, the guard evaluates: does this record meet the condition? No? Skip it. Don't burn tokens. This is **cost control at the record level**.

3. **Context scope is progressive disclosure.** Each step sees *exactly* what it needs—no more. Smaller prompts mean **fewer tokens, less cost, less confusion, better output**.

4. **Batch-native processing.** Point it at a folder of 10,000 records. Granularity controls whether the LLM sees one record, one file, or the whole batch.

5. **Declarative means auditable.** The YAML *is* the pipeline. You can diff it, review it, version it.

6. **Schema enforcement + reprompt.** Every LLM output is validated against a schema. If it doesn't match, reprompt automatically—up to N attempts.

**Put together: you're not wiring API calls—you're declaring a quality-controlled, cost-optimized, multi-model AI pipeline where every record flows through gates, context windows, and validation before anything reaches the output.**

### Design Principles

These opinions come from production use:

- **Configuration Over Code**: Workflow logic belongs in YAML, not Python. This enables auditability, version control, reproducibility, and separation of concerns. Python is available for custom logic (UDFs) but shouldn't be required for standard workflows.
- **Schema-First Validation**: Every LLM output matches a declared schema—catching problems early, enabling automatic retry, and documenting the data contract.
- **Explicit Data Flow**: How data moves between actions is visible. No implicit globals, no hidden state, every field reference is traceable.
- **Fail Fast, Fail Informatively**: Static analysis catches typos, missing references, and configuration errors before expensive LLM calls.
- **Batch by Default**: The framework makes batch the easy path—same workflow, same config, different execution mode.
- **Vendor Agnosticism**: Provider switching requires changing one line. Schema compilation handles vendor-specific formats automatically.
- **Semantic Reusability**: Workflows are domain-agnostic templates. Actions define *what kind of transformation* to perform, not *what domain content* to process. Domain knowledge flows through seed data, not hardcoded prompts. One workflow serves many use cases.
- **Semantic Consistency**: Each action maintains consistent semantic meaning across runs—`extract_facts` always extracts facts, `classify_type` always classifies types. The *what* of each action is invariant; the *content* varies based on input and seed data. This predictability enables reliable pipelines and meaningful static analysis.

---

## Architecture

Agent Actions follows a layered architecture: configuration loading, static analysis, orchestration, action execution, and a multi-vendor provider layer. Each layer has a single responsibility, and they compose into a pipeline that takes YAML configuration and input records and produces validated, structured outputs.

### Data Flow

Records flow through a defined path:

```
staging/           Input records (CSV, JSON, JSONL)
    │
    ▼
source/            Metadata tracking what's processed
    │
    ▼
┌───────────────────────────────────────────┐
│              Action Pipeline               │
│                                           │
│   source.field ──► action_1 ──► output_1  │
│                        │                  │
│                        ▼                  │
│   output_1.field ──► action_2 ──► output_2│
│                        │                  │
│                        ▼                  │
│   output_2.field ──► action_3 ──► final   │
└───────────────────────────────────────────┘
    │
    ▼
target/            Final outputs
```

Each action receives context (source fields, seed data, upstream outputs) and produces structured output that downstream actions can reference. Workflows can split into parallel branches and merge results automatically.

---

## Core Capabilities

### Declarative Workflow Definition

Workflows are YAML files describing actions and their relationships:

```yaml
name: document-analysis
version: "1.0"

defaults:
  model_vendor: openai
  model_name: gpt-4o-mini
  json_mode: true

actions:
  - name: extract_entities
    prompt: $prompts.Entity_Extraction
    schema: entities_schema

  - name: classify_sentiment
    prompt: $prompts.Sentiment_Analysis
    schema: { sentiment: string, confidence: number }

  - name: generate_summary
    dependencies: [extract_entities, classify_sentiment]
    context_scope:
      observe:
        - extract_entities.entities
        - classify_sentiment.sentiment
    prompt: $prompts.Summarize
    schema: summary_schema
```

### Prompt Store

Prompts live in Markdown files with Jinja2 templating:

```markdown
{prompt Entity_Extraction}
Extract named entities from the following document.

## Document
{{ source.content }}

## Target Categories
{% for category in seed.entity_config.categories %}
- {{ category.name }}: {{ category.description }}
{% endfor %}

## Output Format
Return entities matching the schema.
{end_prompt}
```

Benefits:
- Prompts are readable in any Markdown viewer
- Template variables make dependencies explicit
- Changes tracked in version control
- Reusable across workflows

### Schema Validation with Reprompting

Schemas define expected output structure:

```yaml
# schema/entities_schema.yml
name: entities_schema
type: array
items:
  type: object
  properties:
    name:
      type: string
      description: "Entity name"
    category:
      type: string
      enum: [person, organization, location, product]
    confidence:
      type: number
      minimum: 0
      maximum: 1
  required: [name, category]
```

When LLM output violates the schema, Agent Actions:
1. Parses the validation error
2. Includes error in reprompt context
3. Retries with corrective instructions
4. Fails after configurable attempts

### Context Scoping

Control what data each action receives:

```yaml
context_scope:
  observe:            # Included in LLM context
    - source.content
    - extract_entities.entities
  passthrough:        # Passed to output without LLM seeing
    - source.id
    - source.metadata
  drop:               # Excluded entirely
    - source.raw_html
```

This enables:
- Token optimization (exclude verbose fields from context)
- Data privacy (keep sensitive fields from LLM)
- Output assembly (carry IDs through without reprocessing)

### Guards

Guards evaluate conditions *before* the LLM runs, preventing unnecessary token spend:

```yaml
- name: generate_detailed_analysis
  guard:
    condition: 'consensus_score >= 7'
    on_false: "filter"
```

Record scores 5? The LLM never fires. No tokens burned. No latency spent. Across a batch of 10,000 records, guards can eliminate thousands of unnecessary LLM calls before they happen.

### Parallel Consensus

Run multiple independent LLM evaluations and merge the results:

```yaml
- name: classify_severity
  versions:
    param: classifier_id
    range: [1, 2, 3]
    mode: parallel

- name: aggregate_severity
  kind: tool
  impl: aggregate_votes
  version_consumption:
    source: classify_severity
    pattern: merge
```

Two declarations create three parallel classifiers. Two more merge them.

### Granularity Control

Control whether the LLM sees one record, one file, or the whole batch:

```yaml
- name: extract_claims
  granularity: Record     # One LLM call per record

- name: summarize_file
  granularity: File       # One LLM call per input file

- name: generate_report
  granularity: Batch      # One LLM call across all records
```

### Dynamic Dispatch

Select prompts or schemas at runtime based on context:

```yaml
- name: generate_question
  prompt: dispatch_task('select_prompt_by_type')
  schema: dispatch_task('select_schema_by_type')
```

```python
@udf_tool
def select_prompt_by_type(input_data: dict) -> str:
    question_type = input_data.get("question_type")
    prompts = {
        "UNDERSTANDING": "Explain the concept...",
        "APPLICATION": "Generate a scenario...",
        "ANALYSIS": "Create a diagnostic problem..."
    }
    return prompts.get(question_type, prompts["APPLICATION"])
```

### Grounded Retrieval via Tool Dispatch

This is a pattern that matters in production: **don't let LLMs hallucinate data that should come from your systems**. Use tools to retrieve real data, then let LLMs reason over it.

```yaml
# Step 1: LLM generates search criteria (reasoning)
- name: generate_search_criteria
  dependencies: [validate_description]
  schema:
    genres: array
    keywords: array
    target_audience: string
  prompt: |
    Based on this book's description and BISAC codes,
    generate search criteria to find similar books.

# Step 2: Tool searches YOUR catalog (grounding)
- name: retrieve_candidates
  dependencies: [generate_search_criteria]
  kind: tool
  impl: search_book_catalog  # Queries your real database
  intent: "Retrieve matching books from catalog"

# Step 3: LLM ranks real results (reasoning over facts)
- name: generate_recommendations
  dependencies: [retrieve_candidates]
  prompt: |
    From these books in our catalog, select the top 5:
    {{ retrieve_candidates.matching_books }}
```

The tool is the **abstraction layer**. Vector DB, SQL, JSON files, external API—the workflow doesn't care. This is how Agent Actions implements RAG-like patterns: not through built-in vector DB integration, but through the universal tool abstraction.

### Batch Processing

Submit workflows for asynchronous processing:

```yaml
defaults:
  run_mode: batch
```

```bash
# Submit batch
agac run -a my_workflow
# Batch submitted: batch_abc123

# Check status
agac batch status --batch-id batch_abc123
# Status: completed

# Retrieve results
agac batch retrieve --batch-id batch_abc123

# Retry failures
agac batch retry --batch-id batch_abc123
```

Batch mode uses provider batch APIs for 50% cost savings, with automatic retry chains tracking failures across attempts.

### Multi-Vendor Support

Same workflow, multiple providers:

```yaml
actions:
  - name: cheap_extraction
    model_vendor: groq
    model_name: llama-3.1-8b-instant

  - name: quality_generation
    model_vendor: anthropic
    model_name: claude-sonnet-4-20250514

  - name: fast_validation
    model_vendor: openai
    model_name: gpt-4o-mini
```

Supported providers: OpenAI, Anthropic, Google Gemini, Groq, Mistral, Cohere, Ollama (local).

### User-Defined Functions (UDFs)

Extend workflows with Python:

```python
from agent_actions import udf_tool

@udf_tool
def flatten_questions(input_data: dict) -> list:
    """Transform nested questions array to flat records."""
    questions = input_data.get("questions", [])
    return [
        {
            "question_id": f"q_{i}",
            "question_text": q.get("text"),
            "source_id": input_data.get("source_id")
        }
        for i, q in enumerate(questions)
    ]
```

Reference in workflow:

```yaml
- name: flatten_questions
  kind: tool
  impl: flatten_questions
  granularity: Record
```

### Debugging

Full input/output logging for every action, with rendered prompts captured so you can see exactly what the LLM received:

```yaml
- name: extract_facts
  prompt_debug: true    # Log the fully rendered prompt
```

Deterministic pipeline structure means only LLM responses vary—artifacts are stored for replay and debugging.

### IDE Integration (Language Server Protocol)

Agent Actions includes a built-in Language Server Protocol (LSP) that brings IDE-quality navigation to workflows. When you Ctrl+Click on `$prompts.Extract_Facts`, you jump directly to the prompt definition—no manual searching.

**Features:**
- **Go to Definition**: Navigate from references to source (prompts, tools, schemas, actions)
- **Hover Previews**: See prompt content or function signatures without leaving your file
- **Autocomplete**: Suggestions for available prompts, tools, and schemas
- **Syntax Highlighting**: Colored `{prompt}` tags and Jinja2 expressions

**Installation:**
```bash
pip install agent-actions   # LSP bundled automatically
agac-lsp --help              # Verify installation
```

The LSP works with VS Code, Neovim, Cursor, and any editor supporting the Language Server Protocol.

### AI Coding Assistant Skills

Agent Actions bundles "skills"—knowledge packages that teach AI coding assistants (Claude Code, OpenAI Codex) how to work with agentic workflows. When you ask an AI assistant for help with a workflow, it has context about YAML syntax, field references, guards, and common patterns.

**Installation:**
```bash
agac skills install --claude   # For Claude Code users
agac skills install --codex    # For OpenAI Codex users
```

This creates a feedback loop: AI assistants help developers build workflows, which process data using other AI models.

---

## Example: Quiz Generation Pipeline

To illustrate what Agent Actions looks like in practice, consider a certification exam quiz generation workflow. The goal: process technical documentation and produce high-quality practice questions at scale. The requirements:

- Process thousands of documentation pages
- Extract testable facts aligned with exam objectives
- Generate scenario-based questions at the appropriate difficulty level
- Create plausible wrong answers (distractors) that test understanding
- Validate question quality against rubrics
- Filter low-quality output before human review

A single question needs multiple LLM calls: extract facts, classify question type, write scenario, generate distractors, score quality, create explanations. Each step depends on previous outputs. Each step can fail. Scale that to thousands of questions and the complexity gets out of hand fast.

With Agent Actions, the entire pipeline is declared in YAML:

```yaml
actions:
  - name: extract_facts
    prompt: $prompts.Fact_Extraction
    schema: candidate_facts_list

  - name: classify_question_type
    dependencies: [extract_facts]
    prompt: $prompts.Classify_Question
    schema: { quiz_type: string, reason: string }
    context_scope:
      observe: [extract_facts.facts]
```

This configuration declares:
- **What** each action does (prompt + schema)
- **When** it runs (dependencies)
- **What data** it receives (context_scope)

The framework handles **how**: dependency resolution, parallel execution, validation, retry, logging.

### The Full Pipeline

This workflow scales to 18 steps:

```
1.  extract_raw_qa          - Extract Q&A from documentation
2.  flatten_raw_questions   - Normalize to individual records
3.  classify_question_type  - Categorize (UNDERSTANDING, APPLICATION, etc.)
4.  get_authoring_prompt    - Select type-specific instructions
5.  write_scenario_question - Generate scenario-based question
6.  fix_options_format      - Normalize output structure
7.  suggest_distractor_counts - Plan distractor word counts
8.  add_answer_text         - Structure correct answer
9.  generate_distractor_1   - Wrong technology/service
10. generate_distractor_2   - Wrong approach/concept
11. generate_distractor_3   - Edge case/misconception
12. reconstruct_options     - Combine into final options
13. score_question_quality  - Evaluate against rubric
14. filter_low_quality      - Remove score < 85
15. generate_feynman_explanation - Create learner explanation
16. generate_concept_explanation - Explain underlying concept
17. options_combiner        - Final assembly
18. format_quiz_text        - Output formatting
```

This pipeline mixes LLM actions (prompts + schemas) with tool actions (Python UDFs). Some steps run in parallel. Some conditionally skip records. The framework manages it all.

### Patterns Demonstrated

**Mixed Action Types:** LLM actions and tool actions coexist in the same pipeline:
```yaml
- name: classify_question_type    # LLM action
  prompt: $prompts.Classify
  schema: { quiz_type: string }

- name: flatten_questions         # Tool action
  kind: tool
  impl: flatten_questions
```

**Quality Gates with Guards:** Conditional execution filters records mid-pipeline:
```yaml
- name: generate_explanation
  guard:
    condition: 'question_status == "KEEP"'
    on_false: "filter"
```

**Decomposed Generation:** Complex outputs are built through multiple focused steps rather than one mega-prompt:
```
write_scenario_question → generate_distractor_1 → generate_distractor_2 →
generate_distractor_3 → reconstruct_options
```

**Scoring and Filtering:** Generate → Score → Filter is a common pattern:
```yaml
- name: score_question_quality
  schema: question_quality_score

- name: filter_low_quality_questions
  kind: tool
  impl: filter_questions_by_score    # Keep only score >= 85
```

**Dynamic Prompt Selection:** Runtime context determines which prompt variant to use:
```yaml
- name: get_authoring_prompt
  kind: tool
  impl: handle_quiz_type    # Returns different prompts per question type
```

**Parallel Independence:** Actions without dependencies run concurrently:
```
extract_facts
    ├── analyze_sentiment   (parallel)
    └── extract_entities    (parallel)
         └── merge_results
```

These patterns compose. The framework handles orchestration; you focus on the transformation logic.

### Semantic Reusability: One Workflow, Many Domains

The same 18-step workflow can generate questions for *any* certification exam. Data engineering, cloud architecture, law, medicine — the pipeline structure remains identical. Only the seed data changes.

This works because prompts reference seed-level definitions rather than hardcoded content:

```markdown
{prompt Extract_Raw_QA}
Extract testable knowledge for the {{ seed.exam_syllabus.exam_name }}.

**Platform**: {{ seed.exam_syllabus.platform_name }}

{{ seed.exam_syllabus.audience_profile.description }}

**Target Responsibilities**:
{% for resp in seed.exam_syllabus.audience_profile.responsibilities %}
- {{ resp }}
{% endfor %}
...
{end_prompt}
```

To generate questions for a different certification:
1. Create new seed file (`law_bar_exam_syllabus.json`)
2. Point workflow to new seed
3. Run the same workflow

The prompts dynamically inject domain context. No code changes. No prompt rewrites.

| Action | Semantic Purpose | Data Engineering | Law Certification |
|--------|------------------|------------------|-------------------|
| `extract_raw_qa` | Extract testable Q&A | Cloud service facts | Legal precedent facts |
| `classify_question_type` | Categorize by cognitive level | UNDERSTANDING, APPLICATION | UNDERSTANDING, APPLICATION |
| `write_scenario_question` | Generate scenario-based question | "Your team is migrating..." | "Your client is facing..." |
| `score_question_quality` | Evaluate against rubric | Aligned to AWS objectives | Aligned to bar exam topics |

The workflow is a **semantic template**. Actions don't encode domain knowledge—they encode *what kind of transformation* to perform. Domain knowledge lives in seed data and flows through dynamically.

### Beyond Quiz Generation

The patterns demonstrated here apply to any structured extraction use case:

- Document processing pipelines
- Content classification and enrichment
- Data transformation workflows
- Quality assurance automation

The book catalog enrichment example (included in the repository) demonstrates the same patterns in a different domain: 11 steps, BISAC classification, grounded retrieval, parallel branches, quality scoring, and user-specific views.

---

## Design Skill Over Model Size

Most teams default to throwing the biggest model at every problem. GPT-4 for classification. GPT-4 for formatting. GPT-4 for a yes/no check. It works, but it's lazy engineering, and it's expensive. The real skill in building LLM workflows isn't picking the most powerful model. It's decomposing problems so that small, cheap, open-source models can do the work reliably.

Agent Actions is built around this idea. Task decomposition isn't a workaround for budget constraints. It's better engineering.

### Why Decomposition Outperforms Big Models

A single GPT-4 call doing classification + generation + validation in one prompt is fighting itself. The model has to hold too many objectives at once. Break that into three focused steps and something happens: a small model classifying into 4 categories outperforms a large model juggling five tasks simultaneously. The small model has one job. It does it well.

This is the same principle that makes Unix pipes powerful. Small tools that do one thing, composed into pipelines. Agent Actions applies that to LLM workflows.

```yaml
# Small model classifies (one job, high accuracy)
- name: classify_type
  model_vendor: ollama
  model_name: llama3.1:8b       # Free, runs on your laptop
  schema: { type: string }

# Python handles the logic (free, deterministic, never hallucinates)
- name: select_prompt
  kind: tool
  impl: select_prompt_by_type   # No LLM needed

# Small model generates with tight instructions (focused task)
- name: generate_content
  model_vendor: groq
  model_name: llama-3.1-8b     # Fast, cheap
```

Three things make this work:

1. **Each action does one thing.** Focused prompts with focused schemas. A small model doesn't need to be smart. It needs to be focused.

2. **Deterministic logic stays in code.** Math, formatting, filtering, data transformation — these don't need LLMs at all. UDFs handle them with zero cost and zero hallucination. Every task you move from LLM to UDF is money saved and reliability gained.

3. **Schema validation catches mistakes.** If a small model produces invalid output, reprompting fixes it. You don't need a smarter model. You need a feedback loop. The reprompt shows the model exactly what went wrong and gives it another shot.

4. **Guards kill waste early.** Bad records get filtered before they reach expensive downstream steps. Across 10,000 records, this can eliminate thousands of unnecessary LLM calls.

| Approach | Model | Cost per 1M tokens |
|----------|-------|-------------------|
| Monolithic prompt | GPT-4o | $5.00 |
| Decomposed pipeline | GPT-4o-mini | $0.15 |
| Decomposed + open-source | Ollama (Llama 3) | $0.00 |

That's not a small difference. That's 33x cheaper with a commercial small model, or free with an open-source one running locally. And in many cases, the decomposed pipeline produces *better* output because each step has cleaner context and a tighter objective.

### The Engineering Skill Argument

Here's what this really means. When your pipeline depends on GPT-4 for everything, your competitive advantage is your API budget. Whoever can afford to burn more tokens wins. That's not engineering. That's spending.

When your pipeline is decomposed into focused steps with small models, your competitive advantage is your *design*. How you break down the problem. Which steps are LLM vs. deterministic. How tight your prompts are. How smart your guard conditions are. That's engineering. And it rewards skill, not spending.

The best pipelines we've seen use large models for *zero* steps. They run entirely on open-source models (Llama, Mistral, Qwen) through Ollama or Groq, with careful decomposition making up for what the models lack in raw reasoning power. The YAML is identical to a pipeline using GPT-4. Only the `model_vendor` and `model_name` lines change.

```yaml
# This entire pipeline runs for free on a laptop
defaults:
  model_vendor: ollama
  model_name: llama3.1:8b
```

Or use a **hybrid approach** — open-source models for volume, paid APIs only where you genuinely need them:

```yaml
actions:
  - name: bulk_extraction
    model_vendor: ollama           # Free, local — handles 100% of records
    model_name: mistral:7b

  - name: final_polish
    model_vendor: openai           # Paid, but guards mean only 5% of records reach here
    model_name: gpt-4o-mini
```

### Global Access

API costs that seem reasonable in Silicon Valley are prohibitive in Lagos, Nairobi, Dhaka, and Bogota. A single GPT-4 pipeline processing 10,000 records can cost more than a month's salary for a developer in many countries. That prices out talented engineers from building with AI entirely.

Agent Actions breaks this barrier. The framework runs the same workflows with open-source models on commodity hardware. A developer in Lagos with a laptop and Ollama can build the same production-grade pipeline that a well-funded team in San Francisco builds with paid APIs. The workflow YAML is identical. The prompts are identical. The schemas are identical. The validation is identical. Only the vendor line is different.

This isn't charity. It's the natural outcome of good engineering. When you decompose problems properly and use the right model for each step, you don't *need* expensive models. The skill is in the decomposition, not the model selection. And skill doesn't cost money.

A startup in Nigeria competing against one in New York doesn't need to match their API budget. They need to match their engineering. With Agent Actions, they can.

| Old Paradigm | New Paradigm |
|--------------|--------------|
| Throw GPT-4 at everything | Design smart decomposition |
| Pay for more tokens | Write better prompts |
| Scale with money | Scale with architecture |
| API budget determines capability | Engineering skill determines capability |
| Big vendors gatekeep access | Open-source models level the field |

### Environmental Impact

The shift from large to small models isn't just about cost. It's about sustainability:

| Model Size | Relative Energy | CO2 per 1M tokens* |
|------------|-----------------|-------------------|
| GPT-4 class | 10x baseline | ~50g CO2 |
| GPT-4o-mini class | 1x baseline | ~5g CO2 |
| Local (Ollama) | Varies | Near-zero marginal |

*Estimates based on model size ratios and industry benchmarks. Actual figures vary by provider infrastructure, data center location, and energy mix.

Processing 1 million documents: ~50kg CO2 with monolithic GPT-4 vs. ~5kg CO2 with decomposed small models. At scale, better engineering is also greener engineering.

---

## Agentic Design Patterns

Andrew Ng identified [four design patterns for AI agentic workflows](https://x.com/AndrewYNg/status/1773393357022298617): **Reflection**, **Tool Use**, **Planning**, and **Multi-Agent Collaboration**. Agent Actions implements all four, but through configuration rather than imperative code.

### 1. Reflection Pattern

AI systems evaluate and refine their own outputs. Agent Actions does this through **schema validation and reprompting**. When output violates the schema, the framework captures the validation error, includes it in the retry prompt, and gives the LLM a chance to self-correct (see *Core Capabilities > Schema Validation*).

For deeper reflection, create dedicated evaluation actions:

```yaml
- name: generate_draft
  prompt: $prompts.Generate_Draft
  schema: draft_schema

- name: critique_draft
  dependencies: [generate_draft]
  context_scope:
    observe: [generate_draft.content]
  prompt: |
    Review this draft for accuracy and completeness.
    Identify specific errors or improvements needed.
  schema: { critique: string, issues: array, score: number }

- name: improve_draft
  dependencies: [critique_draft]
  guard:
    condition: 'critique_draft.score < 80'
    on_false: skip
  context_scope:
    observe:
      - generate_draft.content
      - critique_draft.critique
      - critique_draft.issues
  prompt: |
    Improve this draft based on the critique.
    Address each identified issue.
  schema: draft_schema
```

This implements the **two-agent reflection pattern**: one action generates, another critiques, and a third improves based on feedback. The quiz pipeline's Score → Filter pattern is another form of quality-based reflection at scale.

### 2. Tool Use Pattern

AI expands its capabilities by integrating with external resources. UDFs make this a **first-class feature** (see *Core Capabilities > User-Defined Functions*).

What's different here: Tool Use in Agent Actions is **deterministic**. The model doesn't decide which tool to call. The workflow **declares** tool usage explicitly. You know exactly when tools execute.

**Hybrid LLM + Tool Pipelines** follow the central principle: **LLM for language, tools for logic**:

```yaml
actions:
  # LLM extracts entities (language understanding)
  - name: extract_entities
    prompt: $prompts.Extract_Entities
    schema: entities_schema

  # Tool enriches with external data (deterministic)
  - name: enrich_entities
    kind: tool
    impl: lookup_entity_metadata
    dependencies: [extract_entities]

  # LLM generates report (language generation)
  - name: generate_report
    dependencies: [enrich_entities]
    prompt: Generate a report on these enriched entities...
```

### 3. Planning Pattern

Break complex tasks into smaller steps with clear sequencing. Agent Actions **is a planning framework**. The workflow YAML *is* the plan:

```yaml
actions:
  - name: extract_facts           # Step 1
  - name: classify_type           # Step 2 (depends on 1)
    dependencies: [extract_facts]
  - name: generate_question       # Step 3 (depends on 2)
    dependencies: [classify_type]
  - name: validate_question       # Step 4 (depends on 3)
    dependencies: [generate_question]
```

This is **static planning**—the execution order is determined at configuration time, not dynamically by an LLM:

| Aspect | Dynamic Planning (LLM decides) | Static Planning (Agent Actions) |
|--------|-------------------------------|--------------------------------|
| Predictability | Low—LLM may choose different paths | High—same config, same execution |
| Debugging | Hard—must trace LLM decisions | Easy—read the YAML |
| Reliability | Varies with LLM reasoning | Consistent |
| Cost | Extra tokens for planning prompts | Zero planning overhead |

The framework builds a dependency graph and executes actions in topological order. Independent actions run concurrently, giving you **implicit parallelization** just from declared dependencies.

Static planning works best for **structured extraction workflows** where you know the task decomposition in advance. For truly open-ended tasks, dynamic planning may be more appropriate.

### 4. Multi-Agent Collaboration Pattern

In Agent Actions, **each action is effectively an agent** with a specific role:

```yaml
actions:
  # "Researcher" agent - extracts facts
  - name: fact_extractor
    prompt: $prompts.Extract_Facts
    model_vendor: anthropic
    model_name: claude-haiku-4-5-20251001

  # "Classifier" agent - categorizes content
  - name: content_classifier
    dependencies: [fact_extractor]
    prompt: $prompts.Classify_Content
    model_vendor: groq
    model_name: llama-3.1-8b

  # "Writer" agent - generates final content
  - name: content_writer
    dependencies: [content_classifier]
    prompt: $prompts.Write_Content
    model_vendor: openai
    model_name: gpt-4o

  # "QA" agent - validates output
  - name: quality_validator
    dependencies: [content_writer]
    prompt: $prompts.Validate_Quality
    model_vendor: anthropic
    model_name: claude-haiku-4-5-20251001
```

Each action has a focused responsibility, uses a model optimized for its task, and communicates through explicit context scoping. Independent actions execute concurrently. Dependencies define the collaboration order.

| Aspect | Agent Actions | Conversational Multi-Agent Frameworks |
|--------|--------------|---------------------------------------|
| Agent definition | YAML actions | Python classes |
| Communication | Context scoping | Message passing |
| Orchestration | DAG execution | Conversation loops |
| Predictability | High (static plan) | Variable (emergent) |
| Best for | Structured pipelines | Open-ended collaboration |

The multi-agent approach here is **choreographed**, not **conversational**. Agents don't negotiate or debate. They execute defined roles in sequence. You trade flexibility for reliability, which is the right trade-off for production data pipelines.

### Pattern Summary

| Pattern | Agent Actions Implementation |
|---------|------------------------------|
| **Reflection** | Schema validation + reprompting; explicit critique actions; score-filter patterns |
| **Tool Use** | UDFs with `kind: tool`; deterministic Python functions; hybrid LLM+tool pipelines |
| **Planning** | Declarative DAG-based workflows; static planning for predictability; dynamic dispatch for runtime decisions |
| **Multi-Agent** | Specialized actions as agents; different models per role; context scoping as communication |

### Other Patterns in the Ecosystem

Beyond Ng's four core patterns, the agentic AI literature discusses additional approaches:

- **ReAct (Reasoning + Acting)**: Alternates between reasoning traces and actions in a loop. Agent Actions' static DAG differs—planning happens at configuration time, not runtime. For use cases requiring dynamic reasoning loops, graph-based state machine frameworks or custom implementations may be more appropriate.

- **Human-in-the-Loop (HITL)**: Human review/approval at decision points. Agent Actions includes a built-in HITL provider (`kind: hitl`) that pauses pipeline execution for manual review at decision points. Guards and UDFs provide additional filtering points where records can be routed to human queues.

- **Memory/State Persistence**: Maintaining context across interactions. Agent Actions workflows are currently stateless per-record—each record processes independently. For conversational memory or cross-record learning, external state management would be needed. This is an area for future development.

---

## Industry Adoption

The problems LLM application developers face keep showing up in forums, blogs, and research papers. Agent Actions addresses many of them directly.

### "Death by Abstraction"

> "Five layers of abstraction just to change a minute detail" — Hacker News
> "Frameworks that wrap 2 lines of code with 2 thousand lines of code" — Hacker News (paraphrased)

Agent Actions' YAML configuration is flat and explicit—what you write is what executes. Errors map directly to configuration lines, not framework internals.

### Unreliable JSON and Schema Validation

> "Asking even a top-notch LLM to output well-formed JSON simply fails sometimes" — Hacker News
> "A malformed JSON response is obvious. A perfectly structured response that subtly misunderstands your requirements is a time bomb."

Schema validation is mandatory, with automatic reprompting on failure (see *Core Capabilities > Schema Validation*).

### Prompt Sprawl and Version Chaos

> "One SaaS company had 47 copies of their 'standard summarization prompt' across their codebase." — V2 Solutions
> "Making changes requires redeploying your entire application"

Centralized prompt store with git-tracked Markdown files:

```
prompt_store/
├── extraction.md      # All extraction prompts
├── validation.md      # All validation prompts
└── generation.md      # All generation prompts
```

### Batch Processing Complexity

> "The most important part of making OpenAI's batch processing API work is building a reliable polling system"
> "Manual file handling: Preparing JSONL files, uploading, polling for completion, downloading results"

Single config flag: `run_mode: batch`. The framework handles everything else (see *Core Capabilities > Batch Processing*).

### Cascading Errors in Multi-Step Pipelines

> "73% of task failures stem from cascading errors, where a single root-cause error triggers multiple downstream failures" — arXiv research

Static analysis catches errors *before* execution. Guards filter records mid-pipeline. Full logging of each action's input/output for debugging.

### Hidden Costs and Opaque LLM Calls

> "RAG systems using heavy abstraction layers can cost 2-3x more than direct API implementations" — community benchmarks

Every LLM call is explicit in configuration. Context scoping controls what gets sent (see *Core Capabilities > Context Scoping*).

### Non-Deterministic Debugging

> "Traditional monitoring tools fail to address prompt-completion correlation"

Full input/output logging, rendered prompt capture, and `prompt_debug: true` for template expansion (see *Core Capabilities > Debugging*).

### Testing and Evaluation Gaps

> "Unlike traditional code, prompts don't throw errors. They might work sometimes, fail silently, or degrade subtly over time"

Pre-flight validation provides structural analysis before execution:

```bash
$ agac schema -a my_workflow

Workflow Schema Analysis
━━━━━━━━━━━━━━━━━━━━━━━━
Action: extract_facts
  Input: source.content, source.url
  Output: facts (array), count (integer)

Action: validate_facts
  Dependencies: extract_facts
  Input: extract_facts.facts
  Output: validated_facts (array)
```

### Vendor Lock-in Anxiety

> "Today's best model is tomorrow's legacy system"

Multi-vendor support with one-line provider switching (see *Core Capabilities > Multi-Vendor Support*).

### Collaboration Bottlenecks

> "Non-technical domain experts often lack the technical skills to modify prompts directly in the codebase"

Prompts in Markdown, YAML config readable without Python knowledge, git-based collaboration with clear diffs.

### Summary

| Industry Pain Point | Agent Actions Solution |
|--------------------|----------------------|
| Over-abstraction | Flat YAML configuration |
| Unreliable JSON | Schema validation + reprompting |
| Prompt sprawl | Centralized prompt store |
| Batch complexity | `run_mode: batch` + retry chains |
| Cascading errors | Static analysis + guards |
| Hidden costs | Explicit calls + context scoping |
| Debugging difficulty | Full logging + prompt_debug |
| Testing gaps | Pre-flight validation |
| Vendor lock-in | Multi-vendor support |
| Collaboration bottlenecks | Markdown prompts + readable YAML |

---

## When to Use Agent Actions

- Structured extraction from documents at scale
- Multi-step agentic pipelines with validation
- Batch processing large datasets
- Teams wanting auditable, version-controlled workflows
- Production workloads requiring reliability

---

## Real-World Impact

Agent Actions has been running in production workflows processing thousands of records. Here are representative results from a quiz generation pipeline:

| Metric | Before (Python scripts) | After (Agent Actions) |
|--------|------------------------|----------------------|
| Records processed/day | ~200 | ~2,000 |
| Failed records requiring manual review | 15% | 3% |
| Time to debug production issues | Hours | Minutes |
| Cost per 1000 records | Baseline | ~50% (batch savings) |
| Time to add new output type | Days | Hours |

The declarative approach pays off most in maintainability. Requirements change? Updating prompts and schemas takes hours, not days. New team member? They can understand workflows by reading YAML instead of tracing Python.

---

## Conclusion

Agent Actions was built for production-scale LLM workflows. The kind where 18 steps, thousands of records, and real SLAs demand reliability that prototype scripts can't provide.

Pull orchestration out into declarative configuration. Define what each action does. Let the framework handle how. Validate before executing. Retry when things fail. Track everything.

But here's what matters more: workflows should be semantic templates, not domain-specific scripts. The same 18-step quiz generation pipeline that produces AWS certification questions can produce bar exam questions with zero code changes. Swap the seed data, run the same workflow. `extract_facts` always extracts facts. `validate_quality` always validates quality. The domain knowledge flows through dynamically.

This separation of *transformation logic* from *domain content* enables:
- Build once, deploy across domains
- Improvements benefit all use cases
- Predictable behavior enables static analysis
- New domains require data, not engineering

And the framework proves something we believe strongly: the best AI pipelines aren't built by whoever has the biggest API budget. They're built by engineers who know how to decompose problems, write tight prompts, and let small open-source models do focused work. That's a skill. It runs on a laptop. And it works anywhere in the world.

Agent Actions is open source under the MIT License.

---

## Getting Started

```bash
# Install
pip install agent-actions

# Initialize project
agac init my-project
cd my-project

# Analyze workflow schema
agac schema -a sample_workflow

# Execute workflow
agac run -a sample_workflow
```

Documentation: [https://muizzkolapo.github.io/docs.agent-actions](https://muizzkolapo.github.io/docs.agent-actions)

GitHub: [https://github.com/Muizzkolapo/agent-actions](https://github.com/Muizzkolapo/agent-actions)

---

*Agent Actions: Declarative Framework for Agentic LLM Workflows*

*By Muizz Kolapo*
