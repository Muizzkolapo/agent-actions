# Agent Actions: Declarative Framework for Agentic LLM Workflows

**From Internal Tool to Open-Source Framework**

---

## Executive Summary

Agent Actions is a declarative YAML-based framework for orchestrating multi-step agentic LLM workflows. Born from the real-world needs of QanaLabs—an educational technology company generating certification exam questions at scale—Agent Actions addresses the gap between prototype LLM scripts and production-grade data pipelines.

The framework emerged from a simple observation: building reliable LLM workflows requires solving the same problems repeatedly—dependency management, output validation, error handling, batch processing, and multi-vendor support. Rather than embedding this logic in application code, Agent Actions externalizes it into configuration, creating auditable, version-controlled pipelines that separate orchestration concerns from business logic.

This whitepaper traces the journey from internal tool to open-source framework, explaining the design decisions, architectural choices, and lessons learned along the way.

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

**LangChain/LlamaIndex**: Python-first frameworks with extensive abstractions. Powerful for complex agentic applications, but the abstraction layers can obscure what's actually happening. Debugging requires understanding framework internals. Configuration lives in Python code, making non-developer review difficult.

**Custom Solutions**: Many teams build internal tools. This works but requires ongoing maintenance, and lessons learned don't transfer between organizations.

The gap: a framework purpose-built for LLM data pipelines—declarative enough for auditing, opinionated enough to solve common problems, flexible enough for real-world complexity.

---

## Origin Story: QanaLabs Quiz Generation

### The Challenge

QanaLabs builds certification exam preparation tools. The core product: generate high-quality practice questions from technical documentation. This sounds simple until you consider the requirements:

- Process thousands of documentation pages
- Extract testable facts aligned with exam objectives
- Generate scenario-based questions at the appropriate difficulty level
- Create plausible wrong answers (distractors) that test understanding
- Validate question quality against rubrics
- Filter low-quality output before human review

A single question requires multiple LLM calls: extract facts → classify question type → write scenario → generate distractors → score quality → create explanations. Each step depends on previous outputs. Each step can fail. Scale this to thousands of questions, and the complexity explodes.

### The First Attempt: Python Scripts

The initial implementation was conventional: Python scripts orchestrating LLM calls. It worked for the first 100 questions. Then:

- **Prompt drift**: Different team members modified prompts without coordination. The "same" workflow produced inconsistent outputs.
- **Silent failures**: LLM outputs occasionally violated expected schemas. Downstream code crashed or produced garbage.
- **Debugging nightmares**: When a question was wrong, tracing back through 8 LLM calls to find the source was painful.
- **Cost overruns**: Synchronous processing meant no batch API savings. A single typo could trigger expensive retry loops.

### The Insight

The team realized they were solving the same problems repeatedly:
- Defining what each step expects and produces
- Passing data between steps
- Validating outputs against schemas
- Retrying when validation fails
- Managing API keys and vendor differences
- Tracking what happened for debugging

These problems aren't specific to quiz generation. They're inherent to any multi-step LLM pipeline.

### The Solution: Configuration Over Code

Rather than embedding orchestration logic in Python, the team externalized it:

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

### The 18-Step Pipeline

The production QanaLabs workflow grew to 18 steps:

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

### Patterns Showcased by the QanaLabs Workflow

The 18-step pipeline demonstrates patterns applicable to any structured extraction use case:

**1. Mixed Action Types**
LLM actions and tool actions (Python UDFs) coexist seamlessly:
```yaml
- name: classify_question_type    # LLM action
  prompt: $prompts.Classify
  schema: { quiz_type: string }

- name: flatten_questions         # Tool action
  kind: tool
  impl: flatten_questions
```

**2. Progressive Context Building**
Each step enriches the context for downstream steps:
```
source → extract_facts.facts → classify.quiz_type → generate.question → ...
```
Later actions reference earlier outputs, building richer context incrementally.

**3. Quality Gates with Guards**
Conditional execution filters records mid-pipeline:
```yaml
- name: generate_explanation
  guard:
    condition: 'question_status == "KEEP"'
    on_false: "filter"
```
Records scoring below threshold skip expensive downstream LLM calls.

**4. Decomposed Generation**
Complex outputs are built through multiple focused steps rather than one mega-prompt:
```
write_scenario_question → generate_distractor_1 → generate_distractor_2 →
generate_distractor_3 → reconstruct_options
```
Each distractor step focuses on one type of wrong answer, improving quality.

**5. Context Scoping for Token Efficiency**
Control what each LLM sees vs. what passes through:
```yaml
context_scope:
  observe: [source.content]           # LLM context (tokens)
  passthrough: [source.id, source.url] # Carried to output (no tokens)
  drop: [source.raw_html]              # Excluded entirely
```

**6. Scoring and Filtering Pattern**
Generate → Score → Filter is a common pattern:
```yaml
- name: score_question_quality
  schema: question_quality_score

- name: filter_low_quality_questions
  kind: tool
  impl: filter_questions_by_score    # Keep only score >= 85
```

**7. Dynamic Prompt Selection**
Runtime context determines which prompt variant to use:
```yaml
- name: get_authoring_prompt
  kind: tool
  impl: handle_quiz_type    # Returns different prompts per question type
```

**8. Parallel Independence**
Actions without dependencies can run concurrently:
```
extract_facts
    ├── analyze_sentiment   (parallel)
    └── extract_entities    (parallel)
         └── merge_results
```

These patterns compose. A document processing pipeline might use: mixed actions + context scoping + quality gates + parallel execution. The framework handles orchestration; you focus on the transformation logic.

### Semantic Reusability: One Workflow, Many Domains

A breakthrough realization: the same 18-step workflow could generate questions for *any* certification exam. Data engineering, cloud architecture, law, medicine—the pipeline structure remains identical. Only the seed data changes.

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

**Semantic Consistency**

Each action maintains consistent semantic meaning across domains:

| Action | Semantic Purpose | Data Engineering | Law Certification |
|--------|------------------|------------------|-------------------|
| `extract_raw_qa` | Extract testable Q&A | Cloud service facts | Legal precedent facts |
| `classify_question_type` | Categorize by cognitive level | UNDERSTANDING, APPLICATION | UNDERSTANDING, APPLICATION |
| `write_scenario_question` | Generate scenario-based question | "Your team is migrating..." | "Your client is facing..." |
| `score_question_quality` | Evaluate against rubric | Aligned to AWS objectives | Aligned to bar exam topics |

The workflow is a **semantic template**. Actions don't encode domain knowledge—they encode *what kind of transformation* to perform. Domain knowledge lives in seed data and flows through dynamically.

This separation enables:
- **Rapid domain expansion**: New certification = new seed file, not new code
- **Consistent quality**: Same validation rubrics apply across domains
- **Shared improvements**: Better distractor generation benefits all domains
- **A/B testing**: Compare seed variations without touching workflow logic

### From Internal Tool to Framework

As the workflow matured, the team recognized the orchestration layer had value beyond quiz generation. The patterns—declarative configuration, schema validation, batch processing, multi-vendor support—apply to any structured extraction use case:

- Document processing pipelines
- Content classification and enrichment
- Data transformation workflows
- Quality assurance automation

Agent Actions was extracted as a standalone framework, refined based on production experience, and released as open source.

---

## Design Principles

The framework embeds opinions learned from production use:

### 1. Configuration Over Code

Workflow logic belongs in YAML, not Python. This enables:
- **Auditability**: Non-developers can review prompts and data flow
- **Version control**: Track changes with git, review in PRs
- **Reproducibility**: Same config produces same behavior
- **Separation of concerns**: Business logic (prompts) vs. infrastructure (orchestration)

Python is available for custom logic (UDFs) but shouldn't be required for standard workflows.

### 2. Schema-First Validation

Every LLM output should match a declared schema. Benefits:
- **Early failure**: Catch problems before downstream processing
- **Automatic retry**: Reprompt with validation errors
- **Type safety**: Downstream actions know what to expect
- **Documentation**: Schemas document the data contract

### 3. Explicit Data Flow

How data moves between actions should be visible:
```yaml
context_scope:
  observe: [extract_facts.summary]      # LLM sees this
  passthrough: [extract_facts.id]       # Output includes this
  drop: [source.raw_html]               # Excluded from context
```

No implicit globals. No hidden state. Every field reference is traceable.

### 4. Fail Fast, Fail Informatively

Errors should surface before expensive LLM calls:
```
Pre-Flight Validation
━━━━━━━━━━━━━━━━━━━━━━
✅ Schema validation passed
❌ Template error in 'fact_extractor':
   → 'referenced_in' not in context
   → Available: source, seed
   → Fix: Add to 'observe' or check variable name
```

Static analysis catches typos, missing references, and configuration errors.

### 5. Batch by Default

Processing at scale requires batch APIs. The framework should make batch the easy path:
```yaml
defaults:
  run_mode: batch
```

Same workflow, same config—different execution mode. Retry chains track failed records across batch attempts.

### 6. Vendor Agnosticism

Provider switching should require minimal change:
```yaml
# Today
model_vendor: openai
model_name: gpt-4o

# Tomorrow
model_vendor: anthropic
model_name: claude-3-5-sonnet
```

Schema compilation handles vendor-specific formats automatically.

### 7. Semantic Reusability

Workflows should be domain-agnostic templates. Actions define *what kind of transformation* to perform, not *what domain content* to process:

```yaml
# Same action works for any domain
- name: extract_facts
  prompt: |
    Extract facts for {{ seed.exam_syllabus.exam_name }}.
    Focus on {{ seed.exam_syllabus.platform_name }}.
```

Domain knowledge flows through seed data, not hardcoded prompts. One workflow serves many use cases.

### 8. Semantic Consistency

Each action should maintain consistent semantic meaning across runs:

- `extract_facts` always extracts facts
- `classify_type` always classifies types
- `validate_quality` always validates quality

The *what* of each action is invariant. The *content* varies based on input and seed data. This predictability enables reliable pipelines and meaningful static analysis.

---

## Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLI (agac)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Config    │  │   Static    │  │      Orchestration      │  │
│  │   Loader    │  │  Analyzer   │  │        Engine           │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         │                │                     │                 │
│         ▼                ▼                     ▼                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Action Executor                          ││
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        ││
│  │  │ Prompt  │  │ Schema  │  │   LLM   │  │Response │        ││
│  │  │ Render  │  │ Compile │  │ Invoke  │  │ Validate│        ││
│  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        ││
│  └───────┼────────────┼────────────┼────────────┼──────────────┘│
│          │            │            │            │                │
│          ▼            ▼            ▼            ▼                │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Provider Layer                           ││
│  │   OpenAI │ Anthropic │ Gemini │ Groq │ Mistral │ Ollama    ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Subsystems

**Configuration Loading**
- Parses YAML workflows
- Resolves prompt store references (`$prompts.Name`)
- Loads seed data and schemas
- Validates structure before execution

**Static Analysis**
- Builds dependency graph
- Detects circular dependencies
- Validates field references
- Checks template syntax
- Verifies UDF availability

**Orchestration Engine**
- Topological sort for execution order
- Parallel execution of independent actions
- Concurrency limiting
- Progress tracking

**Action Executor**
- Prompt rendering (Jinja2 + field references)
- Schema compilation (vendor-specific formats)
- LLM invocation (sync/batch)
- Response validation
- Reprompting on failure

**Provider Layer**
- Unified interface across vendors
- Batch API integration
- Rate limiting and retry
- Token tracking

### Data Flow Model

Data flows through defined paths:

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

Each action receives context (source fields, seed data, upstream outputs) and produces structured output that downstream actions can reference.

**Parallel Branch Merging via Ancestry Chain:**

When workflows split into parallel branches and merge, records must find their siblings. Agent Actions tracks ancestry through two fields:

- **`parent_target_id`**: Links to immediate parent (enables Diamond/Fan-in patterns)
- **`root_target_id`**: Links to original ancestor (enables Map-Reduce patterns)

```
validate ──┬── seo ────────┐
           ├── recs ───────┼── merge (finds all siblings via parent_target_id)
           └── level ──────┘
```

This allows merge actions to access all parallel branch outputs without explicit configuration—the ancestry chain handles record correlation automatically.

---

## Key Features

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

A critical pattern for production workflows: **never let LLMs hallucinate data that should come from your systems**. Instead, use tools to retrieve real data, then let LLMs reason over it.

**The Problem:**
```yaml
# DANGEROUS: LLM invents book recommendations
- name: generate_recommendations
  prompt: "Recommend similar books to {{ source.title }}"
  # LLM might hallucinate fake ISBNs, non-existent titles
```

**The Solution: Tool as Retrieval Layer**

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

**The Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│  WORKFLOW (unchanged regardless of backend)                  │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────────┐ │
│  │ LLM: search  │ → │ Tool: query  │ → │ LLM: rank/pick │ │
│  │ criteria     │    │ catalog      │    │ from results   │ │
│  └──────────────┘    └──────┬───────┘    └────────────────┘ │
└─────────────────────────────┼───────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
    ┌────▼────┐         ┌─────▼─────┐        ┌────▼────┐
    │ Vector  │         │   SQL     │        │  JSON   │
    │ (Chroma)│         │ (Postgres)│        │ (Files) │
    └─────────┘         └───────────┘        └─────────┘
```

**Why This Matters:**

| Aspect | Without Grounding | With Tool Dispatch |
|--------|-------------------|-------------------|
| Data accuracy | LLM invents data | Only real records |
| Hallucination | Common | Impossible |
| Auditability | "LLM said so" | Traceable to source |
| Backend changes | Rewrite prompts | Swap tool impl |
| Testing | Hard to verify | Mock the tool |

**Implementation Pattern:**

```python
@udf_tool(input_type=SearchInput)
def search_book_catalog(data: dict) -> dict:
    """
    Abstraction layer - swap backends without workflow changes.
    Today: Vector search. Tomorrow: SQL. Same interface.
    """
    # Vector DB implementation
    import chromadb
    client = chromadb.Client()
    collection = client.get_collection("books")

    results = collection.query(
        query_texts=[data.get('query_text', '')],
        n_results=50,
        where={"genre": {"$in": data.get('genres', [])}}
    )

    return {"matching_books": results['documents']}
```

The tool is the **abstraction layer**. Vector DB, SQL, JSON files, external API—the workflow doesn't care. This separation means:
- Change backends without touching YAML
- Test with mock data
- Scale retrieval independently of LLM logic

**This is how Agent Actions implements RAG-like patterns**: not through built-in vector DB integration, but through the universal tool abstraction. You control the retrieval layer; the framework orchestrates the pipeline.

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
    model_name: claude-3-5-sonnet

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

The LSP works with VS Code, Neovim, Cursor, and any editor supporting the Language Server Protocol. This investment in tooling reflects a core belief: developer experience matters as much as runtime performance.

### AI Coding Assistant Skills

Agent Actions bundles "skills"—knowledge packages that teach AI coding assistants (Claude Code, OpenAI Codex) how to work with agentic workflows. When you ask an AI assistant for help with a workflow, it has context about YAML syntax, field references, guards, and common patterns.

**Installation:**
```bash
agac skills install --claude   # For Claude Code users
agac skills install --codex    # For OpenAI Codex users
```

This creates a feedback loop: AI assistants help developers build workflows, which process data using other AI models. The framework becomes part of the broader AI development ecosystem rather than an isolated tool.

---

## Industry Pain Points Agent Actions Solves

The challenges facing LLM application developers are well-documented across forums, blogs, and research. Agent Actions was designed—often unknowingly—to address many of these systemic issues.

### 1. "Death by Abstraction" (LangChain Fatigue)

**The Pain:**
> "Five layers of abstraction just to change a minute detail" — Hacker News
> "LangChain wraps 2 lines of code with 2 thousand lines of code" — Hacker News
> "Debugging becomes an archaeological dig. Type hints are vague, execution tracing is inconsistent."

**How Agent Actions Solves It:**
- YAML configuration is flat and explicit—no hidden layers
- What you write is what executes
- Errors map directly to configuration lines, not framework internals
- No need to understand class hierarchies to make changes

```yaml
# This is the entire action definition. No hidden magic.
- name: extract_facts
  prompt: $prompts.Fact_Extraction
  schema: facts_schema
  model_vendor: openai
  model_name: gpt-4o-mini
```

---

### 2. Unreliable JSON and Schema Validation

**The Pain:**
> "Asking even a top-notch LLM to output well-formed JSON simply fails sometimes" — Hacker News
> "Structured outputs create a dangerous illusion of reliability. When you receive a perfect JSON response, you naturally tend to trust it more."
> "A malformed JSON response is obvious. A perfectly structured response that subtly misunderstands your requirements is a time bomb."

**How Agent Actions Solves It:**
- Schema validation is mandatory, not optional
- Failed validation triggers automatic reprompting with error context
- JSON repair attempts before giving up
- Validation happens *before* downstream actions receive data

```yaml
- name: extract_entities
  schema: entities_schema      # Validation enforced
  reprompt:
    max_attempts: 3            # Automatic retry on failure
    json_repair: true          # Fix malformed JSON first
    use_llm_critique: true     # LLM analyzes why it failed
    on_exhausted: continue     # Drop record if all attempts fail
```

---

### 3. Prompt Sprawl and Version Chaos

**The Pain:**
> "One SaaS company had 47 copies of their 'standard summarization prompt' across their codebase. Each one had diverged slightly." — V2 Solutions
> "Iterations are often buried in commit messages and .env vars like VERSION_1 and VERSION_1_FINAL"
> "Making changes requires redeploying your entire application"

**How Agent Actions Solves It:**
- Centralized prompt store (Markdown files with `{prompt}` tags)
- Prompts are version-controlled with git
- Reference by name: `prompt: $prompts.Fact_Extraction`
- Change prompts without touching workflow configuration
- Diff-friendly format for code review

```
prompt_store/
├── extraction.md      # All extraction prompts
├── validation.md      # All validation prompts
└── generation.md      # All generation prompts
```

---

### 4. Batch Processing Complexity

**The Pain:**
> "The most important part of making OpenAI's batch processing API work is building a reliable polling system"
> "Manual file handling: Preparing JSONL files, uploading, polling for completion, downloading results"
> "Cascade failures: Once a batch fails due to hitting token limits, subsequent batches queued for the same model will also fail"

**How Agent Actions Solves It:**
- Single config flag switches to batch mode: `run_mode: batch`
- Framework handles JSONL preparation, upload, polling, download
- Retry chains track failed records across batch attempts
- Same workflow works for both realtime and batch

```yaml
defaults:
  run_mode: batch    # That's it. Same workflow, batch execution.
```

```bash
agac batch retry --batch-id batch_abc123  # Retry only failures
agac batch chain-status --batch-id batch_abc123  # See retry history
```

---

### 5. Cascading Errors in Multi-Step Pipelines

**The Pain:**
> "73% of task failures stem from cascading errors, where a single root-cause error triggers multiple downstream failures" — arXiv research
> "A tiny prompt tweak or a flaky tool call can reroute an entire chain, and without proper traces, debugging turns into guesswork"
> "Traditional debugging collapses when facing multi-agent LLM workflows"

**How Agent Actions Solves It:**
- Explicit dependency declarations make data flow visible
- Static analysis catches errors *before* execution
- Each action's output is validated before downstream consumption
- Guards filter records mid-pipeline, preventing wasted LLM calls
- Full logging of each action's input/output for debugging

```yaml
- name: validate_facts
  dependencies: [extract_facts]     # Explicit dependency
  guard:
    condition: 'fact_count > 0'     # Skip if nothing to validate
    on_false: "filter"
```

---

### 6. Hidden Costs and Opaque LLM Calls

**The Pain:**
> "Hidden costs through suboptimal batching and redundant API calls"
> "RAG systems using heavy abstraction layers can cost 2-3x more than direct API implementations" — community benchmarks
> "Broken built-in cost tracking provides unreliable metrics"

**How Agent Actions Solves It:**
- Every LLM call is explicit in configuration
- No hidden prompts or automatic rephrasing
- Token tracking per action
- Batch mode provides 50% cost savings automatically
- Context scoping (`drop`, `observe`) controls what gets sent to LLM

```yaml
context_scope:
  observe: [source.summary]      # Only this goes to LLM
  drop: [source.raw_html]        # This never touches the LLM
  passthrough: [source.id]       # Carried through, no tokens
```

---

### 6b. Smaller Models, Same Results (The Deterministic Advantage)

**The Pain:**
> "We need GPT-4 because our prompts are complex and require strong reasoning"
> "Smaller models fail too often to be usable in production"
> "Local models can't handle our use case"

**The Insight:** When workflows rely on a single LLM call to do everything—understand context, reason, format output, handle edge cases—you need the most capable (expensive) model. But when you decompose work into focused steps with deterministic scaffolding, smaller models excel.

**How Agent Actions Enables Smaller Models:**

1. **Decomposed Tasks**: Each action does one thing. A small model classifying into 4 categories is more reliable than a large model doing classification + generation + validation in one call.

2. **Deterministic Logic in UDFs**: Math, formatting, filtering, data transformation—these don't need LLMs at all. UDFs handle them deterministically.

```yaml
# LLM classifies (simple task, small model works)
- name: classify_type
  model_name: gpt-4o-mini      # $0.15/1M tokens
  schema: { type: string }

# Python handles the logic (free, deterministic)
- name: select_prompt
  kind: tool
  impl: select_prompt_by_type   # No LLM needed

# LLM generates with specific instructions (focused task)
- name: generate_content
  model_name: llama-3.1-8b     # Local or Groq
```

3. **Schema Validation as Safety Net**: If a small model produces invalid output, reprompting catches it. You don't need a smarter model—you need a feedback loop.

4. **Guards Prevent Waste**: Bad outputs get filtered before expensive downstream steps.

**Real Cost Impact:**

| Approach | Model | Cost per 1M tokens |
|----------|-------|-------------------|
| Monolithic prompt | GPT-4o | $5.00 |
| Decomposed + Agent Actions | GPT-4o-mini | $0.15 |
| Decomposed + Local | Ollama (Llama 3) | $0.00 |

**Example: QanaLabs uses gpt-4o-mini for most steps**

The 18-step quiz generation workflow uses `gpt-4o-mini` for classification, extraction, and scoring. Expensive models are reserved only for creative generation where quality variance matters. Deterministic UDFs handle:
- Flattening nested arrays
- Filtering by score threshold
- Formatting final output
- Selecting prompts by type

**The principle**: Let LLMs do what LLMs do best (language understanding, generation). Let code do what code does best (logic, math, formatting). The framework makes this separation natural.

**Environmental Impact: Greener AI**

The shift from large to small models isn't just about cost—it's about sustainability. LLM inference has significant energy and carbon costs:

| Model Size | Relative Energy | CO2 per 1M tokens* |
|------------|-----------------|-------------------|
| GPT-4 class | 10x baseline | ~50g CO2 |
| GPT-4o-mini class | 1x baseline | ~5g CO2 |
| Local (Ollama) | Varies | Near-zero marginal |

*Estimates based on model size ratios and industry benchmarks. Actual figures vary by provider infrastructure, data center location, and energy mix.

At scale, the difference is substantial. Processing 1 million documents:
- **Monolithic GPT-4 approach**: ~50kg CO2 equivalent
- **Decomposed small-model approach**: ~5kg CO2 equivalent

Agent Actions enables this reduction by making decomposition natural. You're not fighting the framework to use smaller models—the architecture encourages it. Deterministic UDFs replace LLM calls entirely for logic tasks, further reducing compute.

**The business case aligns with the environmental case**: Smaller models = lower cost = lower latency = lower carbon footprint. There's no trade-off to make.

**Democratizing AI: Accessible to Developers Everywhere**

API costs that seem reasonable in Silicon Valley can be prohibitive elsewhere. A developer in Lagos, Nairobi, or Jakarta paying $50/month for OpenAI API access faces a fundamentally different economic reality than one in San Francisco.

Agent Actions changes this equation:

1. **Local-first with Ollama**: Run Llama, Mistral, or Phi entirely on local hardware. Zero API costs. Same workflow configuration.

```yaml
defaults:
  model_vendor: ollama
  model_name: llama3.1:8b    # Runs on a laptop
```

2. **Hybrid approaches**: Use local models for high-volume steps (extraction, classification), reserve paid APIs only for steps requiring maximum quality.

```yaml
actions:
  - name: bulk_extraction
    model_vendor: ollama           # Free, local
    model_name: mistral:7b

  - name: final_polish
    model_vendor: openai           # Paid, but only 5% of records reach here
    model_name: gpt-4o-mini
```

3. **Same workflows, different economics**: A quiz generation pipeline that costs $500/month on GPT-4 can run for near-zero on Ollama. The workflow YAML is identical—only the vendor line changes.

**This matters for global AI adoption.** The frameworks that win will be the ones that don't assume unlimited API budgets. Agent Actions' architecture—decomposed steps, deterministic UDFs, multi-vendor support—makes sophisticated AI workflows accessible to developers regardless of geography or budget.

A startup in Nigeria can build the same quality pipelines as one in New York. The framework doesn't care where you are—it cares that your workflow is well-structured.

**Success Based on Skill, Not Budget**

When API costs are the bottleneck, the richest team wins. When the framework enables local models and smart decomposition, the *most skilled* team wins.

Agent Actions shifts competitive advantage from budget to craftsmanship:

| Old Paradigm | New Paradigm |
|--------------|--------------|
| Throw GPT-4 at everything | Design clever decomposition |
| Pay for more tokens | Write better prompts |
| Scale with money | Scale with architecture |
| API budget determines capability | Engineering skill determines capability |

**What matters now:**

1. **Workflow Design**: How cleverly you decompose complex tasks into focused steps
2. **Prompt Craft**: How effectively you instruct smaller models to do specific jobs
3. **Strategic UDF Use**: Knowing when code beats LLM calls
4. **Schema Design**: Structuring outputs so validation catches errors early
5. **Guard Logic**: Filtering bad outputs before they waste downstream compute

A skilled AI engineer with Ollama on a laptop can outperform a well-funded team throwing GPT-4 at poorly-designed monolithic prompts. The framework rewards thoughtful architecture over brute-force spending.

**This is how it should be.** AI engineering should be a craft where creativity and skill matter—not a game where the biggest API budget wins.

---

### 7. Non-Deterministic Debugging

**The Pain:**
> "Unlike traditional software where the same input reliably produces the same output, LLMs can generate different responses to identical prompts"
> "When an AI system produces incorrect output, the root cause could lie anywhere in this complex pipeline"
> "Traditional monitoring tools fail to address prompt-completion correlation"

**How Agent Actions Solves It:**
- Full input/output logging for every action
- Rendered prompts captured (see exactly what LLM received)
- `prompt_debug: true` shows template expansion
- Deterministic pipeline structure—only LLM responses vary
- Artifacts stored for replay and debugging

```yaml
- name: extract_facts
  prompt_debug: true    # Log the fully rendered prompt
```

---

### 8. Testing and Evaluation Gaps

**The Pain:**
> "Unlike traditional code, prompts don't throw errors. They might work sometimes, fail silently, or degrade subtly over time"
> "The fact we're versioning inputs that produce non-deterministic outputs makes this challenging"

**How Agent Actions Solves It:**
- Schema command analyzes workflow structure before execution
- Schema validation provides binary pass/fail signal
- Runtime validation catches issues during execution

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

---

### 9. Vendor Lock-in Anxiety

**The Pain:**
> "Today's best model is tomorrow's legacy system"
> "Teams building on a single vendor's API face migration costs when better options emerge"

**How Agent Actions Solves It:**
- Multi-vendor support: OpenAI, Anthropic, Gemini, Groq, Mistral, Cohere, Ollama
- Change vendor with one line
- Schema compilation handles vendor-specific formats
- Mix vendors in same workflow

```yaml
actions:
  - name: cheap_extraction
    model_vendor: groq              # Fast and cheap
    model_name: llama-3.1-8b

  - name: quality_generation
    model_vendor: anthropic         # High quality
    model_name: claude-3-5-sonnet
```

---

### 10. Collaboration Bottlenecks

**The Pain:**
> "Non-technical domain experts often lack the technical skills to modify prompts directly in the codebase"
> "Prompt iteration is blocked on code deploys"
> "AI products often have non-technical stakeholders who get excluded"

**How Agent Actions Solves It:**
- Prompts in Markdown—readable by anyone
- YAML config readable without Python knowledge
- Change prompts without code deployment
- Git-based collaboration with clear diffs

---

### Summary: Pain Point Coverage

| Industry Pain Point | Agent Actions Solution |
|--------------------|----------------------|
| Over-abstraction | Flat YAML configuration |
| Unreliable JSON | Schema validation + reprompting |
| Prompt sprawl | Centralized prompt store |
| Batch complexity | `run_mode: batch` + retry chains |
| Cascading errors | Static analysis + guards |
| Hidden costs | Explicit calls + context scoping |
| Expensive models required | Decomposition + UDFs enable smaller models |
| Environmental impact | 10x reduction via small models + local inference |
| Global accessibility | Ollama support = zero-cost AI for developers everywhere |
| Debugging difficulty | Full logging + prompt_debug |
| Testing gaps | Pre-flight validation |
| Vendor lock-in | Multi-vendor support |
| Collaboration bottlenecks | Markdown prompts + readable YAML |

---

## Agentic Design Patterns: How Agent Actions Implements Them

Andrew Ng identified [four foundational design patterns for AI agentic workflows](https://x.com/AndrewYNg/status/1773393357022298617): **Reflection**, **Tool Use**, **Planning**, and **Multi-Agent Collaboration**. These patterns represent best practices for building intelligent systems that go beyond simple prompt-response interactions.

Agent Actions implements or enables all four patterns, though through a declarative lens rather than imperative code.

### 1. Reflection Pattern

**The Pattern:** AI systems evaluate and refine their own outputs iteratively. The model generates content, critiques itself, identifies errors or gaps, and improves in a loop.

**How Agent Actions Implements Reflection:**

Agent Actions provides **structured reflection through schema validation and reprompting**:

```yaml
- name: generate_answer
  schema: answer_schema
  reprompt:
    max_attempts: 3
    json_repair: true
    use_llm_critique: true    # LLM critique feeds back for reflection
    critique_after_attempt: 1
    on_exhausted: continue
```

When output violates the schema, the framework automatically:
1. Captures the validation error
2. Includes the error in the retry prompt
3. Gives the LLM a chance to reflect and correct

This is **automated reflection**—the LLM doesn't just retry blindly; it receives specific feedback about what was wrong.

**Explicit Reflection Workflows:**

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

This implements the **two-agent reflection pattern**: one action generates, another critiques, and a third improves based on feedback.

**Score → Filter Pattern:**

The QanaLabs workflow demonstrates reflection at scale:

```yaml
- name: score_question_quality
  schema: { score: number, reasoning: string }

- name: filter_low_quality
  kind: tool
  impl: filter_questions_by_score   # Keep score >= 85
```

Records scoring below threshold are filtered out—a form of quality-based reflection that prevents bad outputs from propagating.

---

### 2. Tool Use Pattern

**The Pattern:** AI expands its capabilities by integrating with external resources—databases, APIs, code execution—rather than relying solely on internal knowledge.

**How Agent Actions Implements Tool Use:**

This is a **first-class feature** through User-Defined Functions (UDFs):

```yaml
- name: fetch_market_data
  kind: tool
  impl: fetch_stock_prices    # Python function
  granularity: Record

- name: analyze_trends
  dependencies: [fetch_market_data]
  context_scope:
    observe: [fetch_market_data.prices]
  prompt: Analyze these price trends...
```

```python
@udf_tool
def fetch_stock_prices(input_data: dict) -> dict:
    """Fetch real-time data from external API."""
    symbols = input_data.get("symbols", [])
    prices = external_api.get_prices(symbols)
    return {"prices": prices, "timestamp": datetime.now().isoformat()}
```

**Tool actions can:**
- Query databases
- Call external APIs
- Execute calculations
- Transform data structures
- Run arbitrary Python code

**The key insight:** Tool Use in Agent Actions is **deterministic**. Unlike LLM-driven tool selection (where the model decides which tool to call), Agent Actions workflows **declare** tool usage explicitly. This provides predictability—you know exactly when tools execute.

**Hybrid LLM + Tool Pipelines:**

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

This pattern—**LLM for language, tools for logic**—is central to Agent Actions' philosophy. It enables smaller models by offloading non-language tasks to deterministic code.

---

### 3. Planning Pattern

**The Pattern:** Complex tasks are broken into smaller, manageable steps with strategic sequencing. The system creates a roadmap of subtasks and determines the execution path.

**How Agent Actions Implements Planning:**

Agent Actions **is fundamentally a planning framework**. The workflow YAML *is* the plan:

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

This is **static planning**—the execution order is determined at configuration time, not dynamically by an LLM. Benefits:

| Aspect | Dynamic Planning (LLM decides) | Static Planning (Agent Actions) |
|--------|-------------------------------|--------------------------------|
| Predictability | Low—LLM may choose different paths | High—same config, same execution |
| Debugging | Hard—must trace LLM decisions | Easy—read the YAML |
| Reliability | Varies with LLM reasoning | Consistent |
| Cost | Extra tokens for planning prompts | Zero planning overhead |

**DAG-Based Execution:**

The framework builds a dependency graph and executes actions in topological order:

```
extract_facts
    ├── classify_type
    │       └── generate_question
    │               └── validate_question
    └── sentiment_analysis (parallel with classify_type)
```

Independent actions run concurrently. This is **implicit parallelization**—you declare dependencies; the framework optimizes execution.

**Dynamic Dispatch for Conditional Planning:**

When you need runtime decisions within the static plan:

```yaml
- name: select_strategy
  kind: tool
  impl: choose_generation_strategy

- name: generate_content
  dependencies: [select_strategy]
  prompt: dispatch_task('get_strategy_prompt')  # Dynamic prompt selection
```

The plan structure is fixed, but individual steps adapt based on context.

**When Dynamic Planning Makes Sense:**

Agent Actions' static planning is ideal for **structured extraction workflows** where the task decomposition is known in advance. For truly open-ended tasks ("research X and write a report"), dynamic planning (LLM decides next steps) may be more appropriate. Agent Actions optimizes for predictability over flexibility.

---

### 4. Multi-Agent Collaboration Pattern

**The Pattern:** Complex tasks are delegated to specialized agents working together, mirroring human team structures. Each agent handles distinct responsibilities while communicating to achieve unified outcomes.

**How Agent Actions Implements Multi-Agent Collaboration:**

In Agent Actions, **each action is effectively an agent** with a specific role:

```yaml
actions:
  # "Researcher" agent - extracts facts
  - name: fact_extractor
    prompt: $prompts.Extract_Facts
    model_vendor: anthropic
    model_name: claude-3-haiku

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
    model_name: claude-3-haiku
```

**Multi-Agent Characteristics Supported:**

1. **Specialized Roles**: Each action has a focused responsibility
2. **Different "Expertise"**: Actions can use different models optimized for their task
3. **Information Passing**: Context scoping controls what each "agent" sees
4. **Parallel Collaboration**: Independent actions execute concurrently
5. **Hierarchical Structure**: Dependencies define the collaboration order

**QanaLabs as Multi-Agent System:**

The 18-step quiz workflow is essentially a team of specialized agents:

| Action (Agent) | Role | "Expertise" |
|----------------|------|-------------|
| `extract_raw_qa` | Researcher | Document analysis |
| `classify_question_type` | Classifier | Cognitive taxonomy |
| `write_scenario_question` | Writer | Question authoring |
| `generate_distractor_1/2/3` | Distractor Specialists | Wrong answer crafting |
| `score_question_quality` | QA Reviewer | Quality assessment |
| `generate_feynman_explanation` | Educator | Explanation writing |

Each "agent" is optimized for its role. The classifier doesn't need GPT-4; the writer might. The framework orchestrates their collaboration.

**Context as Communication:**

Agents communicate through explicit context passing:

```yaml
- name: quality_validator
  context_scope:
    observe:
      - content_writer.content      # Sees writer output
      - content_classifier.category # Sees classification
    passthrough:
      - fact_extractor.source_id    # Carries metadata
```

This is **structured communication**—each agent receives exactly the context it needs, nothing more.

**Comparison to Framework-Based Multi-Agent:**

| Aspect | Agent Actions | AutoGen/CrewAI |
|--------|--------------|----------------|
| Agent definition | YAML actions | Python classes |
| Communication | Context scoping | Message passing |
| Orchestration | DAG execution | Conversation loops |
| Predictability | High (static plan) | Variable (emergent) |
| Best for | Structured pipelines | Open-ended collaboration |

Agent Actions' multi-agent approach is **choreographed** rather than **conversational**. Agents don't negotiate or debate; they execute defined roles in sequence. This trades flexibility for reliability—appropriate for production data pipelines.

---

### Pattern Summary

| Pattern | Agent Actions Implementation |
|---------|------------------------------|
| **Reflection** | Schema validation + reprompting; explicit critique actions; score-filter patterns |
| **Tool Use** | UDFs with `kind: tool`; deterministic Python functions; hybrid LLM+tool pipelines |
| **Planning** | Declarative DAG-based workflows; static planning for predictability; dynamic dispatch for runtime decisions |
| **Multi-Agent** | Specialized actions as agents; different models per role; context scoping as communication |

### Other Patterns in the Ecosystem

Beyond Ng's four core patterns, the agentic AI literature discusses additional approaches:

- **ReAct (Reasoning + Acting)**: Alternates between reasoning traces and actions in a loop. Agent Actions' static DAG differs—planning happens at configuration time, not runtime. For use cases requiring dynamic reasoning loops, consider LangGraph or custom implementations.

- **Human-in-the-Loop (HITL)**: Human review/approval at decision points. Agent Actions doesn't have built-in HITL support, but guards provide natural filtering points where external review could be integrated. Records marked for review can be routed to human queues via UDFs.

- **Memory/State Persistence**: Maintaining context across interactions. Agent Actions workflows are currently stateless per-record—each record processes independently. For conversational memory or cross-record learning, external state management would be needed. This is an area for future development.

Agent Actions implements these patterns through a **declarative, configuration-first lens**. Rather than imperative code orchestrating agents, YAML configuration declares the collaboration structure. This approach prioritizes auditability, predictability, and production reliability—sometimes at the cost of dynamic flexibility.

---

## Comparison to Alternatives

| Aspect | Agent Actions | LangChain | n8n | Custom Python |
|--------|--------------|-----------|-----|---------------|
| **Configuration** | YAML (declarative) | Python (imperative) | Visual (nodes) | Python |
| **Primary audience** | Developers, data teams | Developers | No-code users | Developers |
| **LLM focus** | Purpose-built | Core feature | One of many integrations | Manual |
| **Schema validation** | Built-in with reprompt | Via Instructor/plugins | Limited | Manual |
| **Batch processing** | Native with retry chains | Manual implementation | Event-driven | Manual |
| **Static analysis** | Pre-flight validation | Runtime errors | Runtime errors | Runtime errors |
| **Audit trail** | Git-trackable configs | Code review | Export/import | Code review |
| **Scale model** | Batch-first (10k+ records) | Typically synchronous | Event-triggered | Varies |

**Other Notable Frameworks:**

- **LangGraph** (LangChain ecosystem): Graph-based state machines for complex agent control flow. Better for dynamic routing and cycles; Agent Actions optimizes for linear DAGs.
- **Instructor**: Pydantic-based structured output validation. Similar philosophy to Agent Actions' schema validation, but operates at the single-call level rather than pipeline orchestration.
- **DSPy**: Programmatic prompt optimization through compiler-like abstractions. Complements Agent Actions—DSPy integration is on the roadmap for self-optimizing prompts.
- **AutoGen/CrewAI**: Multi-agent conversation frameworks. Better for open-ended collaboration; Agent Actions provides choreographed (not conversational) multi-agent execution.

### When to Use Agent Actions

**Good fit:**
- Structured extraction from documents at scale
- Multi-step agentic pipelines with validation
- Batch processing large datasets
- Teams wanting auditable, version-controlled workflows
- Production workloads requiring reliability

**Less suited:**
- Conversational agents / chatbots
- RAG applications (no built-in vector DB integration)
- Quick prototyping (more setup than a script)
- Highly dynamic control flow (YAML has limits)

---

## Real-World Impact: QanaLabs Results

After migrating to Agent Actions, QanaLabs observed:

| Metric | Before | After |
|--------|--------|-------|
| Questions generated/day | ~200 | ~2,000 |
| Failed records requiring manual review | 15% | 3% |
| Time to debug production issues | Hours | Minutes |
| Cost per 1000 questions | $X | $0.5X (batch savings) |
| Time to add new question type | Days | Hours |

The declarative approach paid dividends in maintainability. When exam objectives changed, updating prompts and schemas took hours, not days. When new team members joined, they could understand workflows by reading YAML rather than tracing Python.

---

## Roadmap

Agent Actions continues to evolve based on production feedback:

**Recently Shipped:**
- ✅ `agac inspect field-flow` - Visualize data flow, validate field references
- ✅ `agac inspect conflicts` - Detect field name collisions and ambiguities
- ✅ Language Server Protocol (LSP) - IDE integration for VS Code, Neovim, Cursor
- ✅ AI Coding Assistant Skills - Bundled knowledge for Claude Code and OpenAI Codex
- ✅ Ancestry Chain for Parallel Merge - `parent_target_id` and `root_target_id` enable Diamond, Map-Reduce, and Ensemble patterns

**Near-term:**
- Enhanced MCP (Model Context Protocol) integration
- Visual workflow editor
- Workflow templates and scaffolding

**Medium-term:**
- Embedding model support
- Vector database integrations
- Workflow composition (sub-workflows)
- Enhanced observability dashboard

**Long-term:**
- Self-optimizing prompts (DSPy integration)
- Cost estimation before execution
- A/B testing for prompt variants

---

## Conclusion

Agent Actions emerged from solving real problems at scale. The QanaLabs quiz generation workflow—18 steps, thousands of records, production SLAs—demanded reliability that prototype scripts couldn't provide.

The solution: externalize orchestration into declarative configuration. Define what each action does. Let the framework handle how. Validate before executing. Retry when things fail. Track everything.

**The deeper insight**: workflows should be semantic templates, not domain-specific scripts. The same 18-step quiz generation pipeline that produces AWS certification questions can produce bar exam questions—with zero code changes. Swap the seed data, run the same workflow. Actions maintain consistent semantic meaning (`extract_facts` extracts facts, `validate_quality` validates quality) while domain knowledge flows through dynamically.

This separation of *transformation logic* from *domain content* enables:
- Build once, deploy across domains
- Improvements benefit all use cases
- Predictable behavior enables static analysis
- New domains require data, not engineering

This isn't the right tool for every LLM application. Chatbots, RAG systems, and highly dynamic agents may be better served by other approaches. But for structured data extraction at scale—processing documents, generating content, enriching datasets—the declarative model offers maintainability, auditability, and reliability that code-first approaches struggle to match.

Agent Actions is open source under the Elastic License 2.0. We welcome contributions, feedback, and real-world use cases that push the framework forward.

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

*From the team at QanaLabs*
