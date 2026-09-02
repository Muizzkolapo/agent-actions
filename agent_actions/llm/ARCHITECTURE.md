# LLM Module Architecture

This document maps the moving parts of `agent_actions/llm/` — the module that handles all LLM communication, both online (one record at a time) and batch (hundreds of records at once).

---

## High-Level Overview

```
                         agent_actions/llm/
                              │
              ┌───────────────┼───────────────┐
              │               │               │
          config/         realtime/         batch/
       (vendor models)   (online path)    (batch path)
              │               │               │
              └───────┬───────┘               │
                      │                       │
                  providers/                  │
              (7 LLM vendors +            (batch versions
               3 special providers)        of same vendors)
```

The module has **four packages**:

| Package | What it does |
|---------|-------------|
| `config/` | Pydantic models for vendor configuration (temperature, model_name, API keys) |
| `realtime/` | Online path — send one prompt, get one response, synchronously |
| `batch/` | Batch path — submit hundreds of prompts, poll for completion, process results |
| `providers/` | The actual SDK calls to OpenAI, Anthropic, Gemini, etc. |

---

## The Online Path (realtime/)

This is the simpler path. A single record goes in, an LLM response comes out.

```
┌─────────────────────────────────────────────────────────┐
│                   CALLER (workflow engine)               │
│                                                          │
│   OnlineStrategy.invoke()                                │
│     └─ retry + reprompt wrappers                         │
│          └─ _call_llm()                                  │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              run_dynamic_agent()                         │
│              (processing/helpers.py)                     │
│                                                          │
│   1. Guard check — should this record be processed?      │
│   2. Call create_dynamic_agent()                         │
│   3. Validate LLM output against schema                  │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│           create_dynamic_agent()                         │
│           (llm/realtime/builder.py)                      │
│                                                          │
│   THE CENTRAL ORCHESTRATOR — everything routes through   │
│                                                          │
│   Step 1: Validate prompt exists                         │
│   Step 2: Resolve tools_path                             │
│   Step 3: Prepare context data (JSON string for LLMs)    │
│   Step 4: Append observe fields to prompt                │
│   Step 5: Compile output schema for vendor               │
│   Step 6: Debug print (if prompt_debug: true)            │
│   Step 7: ──► Dispatch to provider client ◄──            │
│   Step 8: Merge schema dispatch results into response    │
│                                                          │
│   Returns: list[dict] — one dict per LLM response item   │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│        ClientInvocationService.invoke_client()            │
│        (llm/realtime/services/invocation.py)              │
│                                                          │
│   Routes to the right provider:                          │
│                                                          │
│   CLIENT_REGISTRY = {                                    │
│     "openai":    "...openai.client:OpenAIClient",  ←lazy │
│     "anthropic": "...anthropic.client:AnthropicClient",  │
│     "gemini":    "...gemini.client:GeminiClient",        │
│     "groq":      "...groq.client:GroqClient",            │
│     "cohere":    "...cohere.client:CohereClient",        │
│     "ollama_local/cloud": "...ollama.client:...",        │
│     "tool":      ToolClient,              ←eager         │
│     "hitl":      HitlClient,                             │
│     "agac-provider": AgacClient,                         │
│   }                                                      │
│                                                          │
│   External SDK providers are strings — imported lazily    │
│   on first use so the CLI doesn't crash when an unused    │
│   SDK is missing.                                        │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              BaseClient.invoke()                         │
│              (llm/providers/client_base.py)               │
│                                                          │
│   1. Resolve API key from env var                        │
│   2. Check json_mode flag                                │
│   3. Dispatch to call_json() or call_non_json()          │
│                                                          │
│   Each provider implements these two methods:             │
│   ┌──────────────────────────────────────────┐           │
│   │  call_json():                            │           │
│   │    MessageBuilder.build() → messages      │           │
│   │    SDK_call(messages, schema) → response  │           │
│   │    ResponseBuilder.record_usage()         │           │
│   │    parse_llm_json() → list[dict]          │           │
│   │                                          │           │
│   │  call_non_json():                        │           │
│   │    MessageBuilder.build() → messages      │           │
│   │    SDK_call(messages) → response          │           │
│   │    ResponseBuilder.wrap_non_json()        │           │
│   │    → list[dict]                          │           │
│   └──────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────┘
```

---

## The Batch Path (batch/)

This is the complex path. Hundreds of records go through a multi-phase lifecycle.

```
┌─────────────────────────────────────────────────────────────────┐
│                        BATCH LIFECYCLE                           │
│                                                                  │
│   Phase 1        Phase 2         Phase 3         Phase 4         │
│  ┌────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    │
│  │PREPARE │───▶│ SUBMIT   │───▶│  POLL    │───▶│ PROCESS  │    │
│  │        │    │          │    │          │    │          │    │
│  │Records │    │Send to   │    │Wait for  │    │Parse     │    │
│  │→ Tasks │    │provider  │    │provider  │    │results   │    │
│  │        │    │          │    │to finish │    │          │    │
│  └────────┘    └──────────┘    └──────────┘    └────┬─────┘    │
│                                                      │          │
│                                              ┌───────┴───────┐  │
│                                              │               │  │
│                                         Phase 5         Phase 6  │
│                                        ┌──────────┐  ┌─────────┐│
│                                        │ RETRY    │  │REPROMPT ││
│                                        │          │  │         ││
│                                        │Missing   │  │Failed   ││
│                                        │records?  │  │validn?  ││
│                                        │Resubmit  │  │Resubmit ││
│                                        └──────────┘  └─────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Phase 1: Prepare (preparator.py)

```
Input:  list of raw data records + agent_config
Output: PreparedBatchTasks (tasks + context_map + stats)

For each record:
  ┌─────────────┐     ┌───────────┐     ┌────────────┐
  │ Assign ID   │────▶│ Run guard │────▶│ Build task │
  │ (target_id) │     │ (filter?) │     │ (prompt +  │
  └─────────────┘     └─────┬─────┘     │  content)  │
                            │           └────────────┘
                     ┌──────┴──────┐
                     │  FILTERED   │  → marked in context_map
                     │  SKIPPED    │    but not sent to provider
                     │  INCLUDED   │  → sent to provider
                     └─────────────┘

context_map = {
  "record_123": {
    ...original data...,
    "_batch_filter_status": "included",
    "_passthrough_fields": {"field_a": "value_a"},
  }
}
```

### Phase 2: Submit (submission.py)

```
1. Idempotency check  → already submitted? Return existing batch_id
2. Save context_map   → persisted to StorageBackend metadata
3. Provider submit    → sends JSONL file to provider API
4. Register batch     → saved to StorageBackend metadata (batch_registry:{action})
5. Stamp dispositions → records marked DEFERRED in storage
```

### Phase 3-4: Poll + Process

```
Provider completes → retrieve results → reconcile

Reconciliation (reconciler.py):
  expected_ids = {records we submitted}
  answered_ids = {records the provider answered: success AND content}
  missing_ids  = expected - answered

  For each result:
    ├── Answered    → parse content, merge passthrough fields
    └── Unanswered  → trigger retry (Phase 5); when the attempts run out,
                      an error record if a row came back at all, a tombstone
                      if the provider returned no row for it
```

### Phase 5-6: Recovery State Machine

```
                    ┌─────────────┐
                    │  ORIGINAL   │
                    │   BATCH     │
                    └──────┬──────┘
                           │
                    missing records?
                     ╱            ╲
                   YES             NO
                    │               │
              ┌─────▼─────┐        │
              │   RETRY    │        │
              │ attempt 1  │        │
              └─────┬──────┘        │
                    │               │
              still missing?        │
               ╱         ╲          │
             YES          NO        │
              │            │        │
        ┌─────▼─────┐     │        │
        │   RETRY    │     │        │
        │ attempt 2  │     │        │
        └─────┬──────┘     │        │
              │            │        │
         exhausted?   ┌────▼────┐   │
              │       │ MERGE   │   │
              ▼       │ results │   │
        ┌──────────┐  └────┬────┘   │
        │EXHAUSTED │       │        │
        │(give up) │       │        │
        └────┬─────┘       │        │
             │             │        │
             └──────┬──────┘        │
                    │               │
              validation failing?   │
               ╱         ╲          │
             YES          NO ───────┤
              │                     │
        ┌─────▼──────┐              │
        │  REPROMPT   │              │
        │  attempt 1  │              │
        └─────┬──────┘              │
              │                     │
         still failing?             │
              │                     │
        ┌─────▼──────┐              │
        │  REPROMPT   │              │
        │  attempt 2  │              │
        └─────┬──────┘              │
              │                     │
              ▼                     │
        ┌──────────┐                │
        │ FINALIZE │◄───────────────┘
        │  output  │
        └──────────┘

All state is persisted to StorageBackend metadata between runs:
  recovery_state:{action}:{name}
  batch_registry:{action}
  batch_context:{action}:{name}
```

---

## Record Flow: What Happens to Every Record (Batch)

This traces what happens to each individual record through the batch pipeline.
Real example: you submit 10 records, the provider returns results for 8.

### Step 1: Submission — 10 records go in

```
Input: 10 records from your data file

     Record A ─┐
     Record B  │
     Record C  │    preparator.py
     Record D  ├──────────────────▶  Guard evaluation per record
     Record E  │
     Record F  │
     Record G  │    For each record, one of three things happens:
     Record H  │
     Record I  │    INCLUDED  → sent to provider (gets a target_id)
     Record J ─┘    FILTERED  → guard said "skip this" → never sent
                    FAILED    → error during preparation → never sent

Say records A-H pass the guard, I is filtered, J fails prep:

  context_map = {
    "A": {data..., status: INCLUDED}     ← sent to provider
    "B": {data..., status: INCLUDED}     ← sent to provider
    "C": {data..., status: INCLUDED}     ← sent to provider
    "D": {data..., status: INCLUDED}     ← sent to provider
    "E": {data..., status: INCLUDED}     ← sent to provider
    "F": {data..., status: INCLUDED}     ← sent to provider
    "G": {data..., status: INCLUDED}     ← sent to provider
    "H": {data..., status: INCLUDED}     ← sent to provider
    "I": {data..., status: FILTERED}     ← never sent, disposition written
    "J": {data..., status: FAILED}       ← never sent, disposition written
  }

  8 tasks sent to provider in JSONL file
```

### Step 2: Provider returns results — only 6 come back

```
Provider processes 8 records, returns 6 results + 1 error:

  Result for A  ✓ success, content: {"summary": "..."}
  Result for B  ✓ success, content: {"summary": "..."}
  Result for C  ✓ success, content: {"summary": "..."}
  Result for D  ✗ success=false, error: "content filter violation"
  Result for E  ✓ success, content: {"summary": "..."}
  Result for F  ✓ success, content: {"summary": "..."}
  error_line_7  ✗ provider parsing error (malformed input for G)
  (nothing)     H simply missing — provider dropped it
```

### Step 3: Reconciliation — who's missing?

```
reconciler.py does set math:

  expected  = {A, B, C, D, E, F, G, H}    (8 INCLUDED records)
  answered  = {A, B, C, E, F}              (5 results carrying content)
  error_line = {error_line_7}              (logged as warning, filtered out)
  missing   = expected - answered = {D, G, H}
              D answered with an error and no content, so retry claims it
              alongside the two the provider never returned
```

### Step 4: Process what we have

```
batch_result_strategy.py processes the 5 answered results:

  A → SUCCESS  → parse JSON, merge passthrough fields → output record
  B → SUCCESS  → parse JSON, merge passthrough fields → output record
  C → SUCCESS  → parse JSON, merge passthrough fields → output record
  (D carries no content, so it is not processed here — see Step 5)
  E → SUCCESS  → parse JSON, merge passthrough fields → output record
  F → SUCCESS  → parse JSON, merge passthrough fields → output record

For records that never went to the provider:
  I → FILTERED → passthrough record (original data, no LLM output)
  J → FAILED   → error record from prep failure
```

### Step 5: Retry — try to recover D, G and H

```
retry.py kicks in for the 3 unanswered records:

  ┌─────────────────────────────────────────────────────┐
  │ Retry attempt 1/3                                    │
  │                                                      │
  │   Resubmit {D, G, H} to provider                    │
  │   Provider returns: result for H (success);          │
  │     D errors again, G omitted again                  │
  │                                                      │
  │   D and G still unanswered                           │
  │   H recovered! ✓  Tagged with recovery metadata:     │
  │     retry_attempts: 2, failures: 1, succeeded: true  │
  │                                                      │
  │   missing = {D, G}                                   │
  └─────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────────┐
  │ Retry attempt 2/3                                    │
  │                                                      │
  │   Resubmit {D, G} to provider                        │
  │   Provider returns: nothing                          │
  │                                                      │
  │   D and G still unanswered                           │
  └─────────────────────────────────────────────────────┘
                         │
                         ▼
  ┌─────────────────────────────────────────────────────┐
  │ Retry attempt 3/3                                    │
  │                                                      │
  │   Resubmit {D, G} to provider                        │
  │   Provider returns: D errors again, G nothing        │
  │                                                      │
  │   G → EXHAUSTED (never returned)                     │
  │   D → FAILED, keeping the provider error, with the   │
  │       same exhausted retry history attached          │
  │   build_exhausted_recovery() creates metadata:       │
  │     retry_attempts: 4, failures: 4, succeeded: false │
  └─────────────────────────────────────────────────────┘
```

### Step 6: Final accounting — every record has a disposition

```
┌──────────┬──────────────┬─────────────────────────────────┐
│ Record   │ Disposition  │ What happened                   │
├──────────┼──────────────┼─────────────────────────────────┤
│ A        │ SUCCESS      │ LLM returned valid output       │
│ B        │ SUCCESS      │ LLM returned valid output       │
│ C        │ SUCCESS      │ LLM returned valid output       │
│ D        │ FAILED       │ Provider error, retry spent     │
│ E        │ SUCCESS      │ LLM returned valid output       │
│ F        │ SUCCESS      │ LLM returned valid output       │
│ G        │ EXHAUSTED    │ Never returned after 3 retries  │
│ H        │ SUCCESS      │ Recovered on retry attempt 1    │
│ I        │ FILTERED     │ Guard said skip                 │
│ J        │ FAILED       │ Error during task preparation   │
├──────────┼──────────────┼─────────────────────────────────┤
│ Total    │ 10 records   │ 6 success, 2 failed, 1 exhaust, │
│          │              │ 1 filtered                       │
└──────────┴──────────────┴─────────────────────────────────┘

EVERY record gets a disposition. Nothing is silently lost.
The storage backend records each one for audit.
```

### The disposition types

```
SUCCESS     → LLM returned valid output, written to target
FAILED      → Something went wrong (provider error, prep error, parse error)
EXHAUSTED   → Retried max times, provider never returned this record
FILTERED    → Guard evaluation said "don't process this record"
SKIPPED     → Upstream action didn't produce output for this record
DEFERRED    → Batch submitted but not yet completed (temporary)
PASSTHROUGH → Record passed through without LLM processing
```

### What about reprompt? (validation failures)

After retry recovers missing records, there's an optional validation step.
If the LLM output doesn't pass a user-defined validation function:

```
Say records A and C pass validation, but B fails:

  A → graduated (passed validation) ✓
  B → still_failing → resubmit with corrective feedback
  C → graduated (passed validation) ✓

Reprompt attempt 1:
  B resubmitted with: "Your previous output failed because: ..."
  Provider returns new output for B
  B passes validation → graduated ✓

If B keeps failing after max_attempts:
  B → EXHAUSTED with failure_type_counts metadata
  Policy decides: return last attempt ("return_last") or raise error
```

### Recovery across workflow runs

The batch path is designed to survive crashes. If the workflow stops mid-retry:

```
Run 1:  Submit batch → provider processing...          [crash]
Run 2:  Check registry → batch completed → retrieve    [crash]
Run 3:  Load recovery_state → retry attempt 2 → ...    [success]

State files on disk:
  .batch_registry.json        ← which batches exist, their status
  .context_map_{name}         ← original input data for each record
  .recovery_state_{name}.json ← retry/reprompt progress
```

Each run picks up where the last one left off. No records are reprocessed.

---

## Provider Layer (providers/)

Each vendor has an online client and (usually) a batch client.

```
providers/
├── client_base.py          ← BaseClient: online interface
├── batch_base.py           ← BaseBatchClient: batch interface
├── batch_client_factory.py ← Factory: vendor string → batch client
├── error_wrapper.py        ← Unified error classification
├── generation_params.py    ← Shared param extraction
├── mixins.py               ← JSON parsing, error handling mixins
├── usage_tracker.py        ← Token usage storage (ContextVar)
├── failure_injection.py    ← Test chaos injection
│
├── openai/
│   ├── client.py           ← OpenAIClient (online)
│   └── batch_client.py     ← OpenAIBatchClient
│
├── anthropic/
│   ├── client.py           ← AnthropicClient
│   └── batch_client.py     ← AnthropicBatchClient
│
├── gemini/
│   ├── client.py           ← GeminiClient
│   └── batch_client.py     ← GeminiBatchClient
│
├── groq/
│   ├── client.py           ← GroqClient
│   └── batch_client.py     ← GroqBatchClient
│
├── cohere/
│   └── client.py           ← CohereClient (NO batch support)
│
├── ollama/
│   ├── client.py           ← OllamaLocalClient + OllamaCloudClient
│   └── batch_client.py     ← OllamaBatchClient (simulated via threads)
│
├── hitl/
│   ├── client.py           ← HitlClient (launches Flask server)
│   └── server.py           ← Flask approval UI
│
├── tools/
│   └── client.py           ← ToolClient (runs Python UDFs)
│
└── agac/
    ├── client.py           ← AgacClient (deterministic mock)
    └── batch_client.py     ← AgacBatchClient (auto-complete mock)
```

### How providers differ

| Provider | Online Schema | Batch API | Key Quirk |
|----------|--------------|-----------|-----------|
| OpenAI | `response_format: json_schema` | Native Batch API | Reference implementation |
| Anthropic | Schema sent as `tools` param | Message Batches API | Prompt caching, tool-use extraction |
| Gemini | `response_mime_type: application/json` | Batch Prediction | `max_tokens` → `max_output_tokens` |
| Groq | Same as OpenAI | Native Batch | JSON repair on malformed output |
| Cohere | `response_format: {type: json_object}` | None | `top_p` → `p`, no batch |
| Ollama Local | `format` param with schema | Simulated (threads) | No API key needed |
| Ollama Cloud | Schema injected into prompt text | Simulated (threads) | No structured output support |
| HITL | N/A | N/A | Flask server, human approval |
| Tool | N/A | N/A | Runs Python functions |
| AGAC | Mock | Mock | Quality degrades by attempt (tests reprompt) |

### Error unification

All vendor SDK exceptions collapse to three types:

```
VendorAPIError    ← catch-all for provider errors
├── RateLimitError   ← triggers retry-after backoff
└── NetworkError     ← connection/timeout failures
```

This lets retry logic work uniformly without knowing which provider is in use.

---

## Config Layer (config/)

```
BaseVendorConfig (Pydantic, extra="forbid")
│
│  Shared fields:
│  ├── vendor_type      (enum: openai, anthropic, gemini, ...)
│  ├── api_key_env_name (env var name for API key)
│  ├── model_name       (which model to use)
│  ├── temperature      (0.0 - 2.0)
│  ├── top_p            (0.0 - 1.0)
│  ├── max_tokens       (max response length)
│  ├── json_mode        (true/false)
│  └── default_timeout  (seconds)
│
├── OpenAIConfig      + frequency_penalty, presence_penalty, top_k
├── AnthropicConfig   + anthropic_version, enable_prompt_caching, tools_mode
├── GeminiConfig      + safety_settings, generation_config
├── GroqConfig        (no extras)
├── CohereConfig      + k (top-k), p (top-p)
├── OllamaLocalConfig + base_url (no API key)
├── OllamaCloudConfig + base_url
├── ToolVendorConfig  (placeholder, no LLM)
├── HitlVendorConfig  (placeholder, no LLM)
└── AgacProviderConfig (mock provider)

extra="forbid" means typos in YAML (e.g. "temperture") raise
an error instead of being silently ignored.
```

---

## Key Data Flow: Online vs Batch

```
ONLINE (synchronous, per-record):
  record → prompt → SDK call → response → output
  Time: seconds
  State: in-memory only

BATCH (asynchronous, per-action):
  records → JSONL file → provider API → poll... → results file → process
  Time: minutes to hours
  State: persisted to disk (context_map, registry, recovery_state)

Both paths share:
  - Same provider clients (online vs batch variants)
  - Same schema compiler (ResponseSchemaCompiler)
  - Same error taxonomy (ConfigurationError, VendorAPIError, etc.)
  - Same output enrichment pipeline (UnifiedProcessor)
```

---

## File Index

### Core orchestration
| File | Role |
|------|------|
| `realtime/builder.py` | Online entry point — the function everything routes through |
| `realtime/services/invocation.py` | Client registry + lazy import + dispatch |
| `batch/services/submission.py` | Batch submit: prepare → save → submit → register |
| `batch/services/processing.py` | Batch process: retrieve → reconcile → retry → reprompt → finalize |
| `batch/processing/preparator.py` | Per-record task preparation + context_map building |
| `batch/processing/reconciler.py` | Expected vs answered ID math, missing detection |
| `batch/processing/batch_result_strategy.py` | Convert BatchResult → ProcessingResult |

### Recovery
| File | Role |
|------|------|
| `batch/services/retry.py` | Retry facade |
| `batch/services/retry_ops.py` | Resubmit missing records |
| `batch/services/reprompt_ops.py` | Validation + reprompt loop |
| `batch/services/processing_recovery.py` | Recovery state machine |
| `batch/infrastructure/recovery_state.py` | RecoveryState persistence |

### Infrastructure
| File | Role |
|------|------|
| `batch/infrastructure/registry.py` | Thread-safe batch job registry |
| `batch/infrastructure/context.py` | Context map save/load |
| `batch/infrastructure/batch_client_resolver.py` | Cached provider resolution |
| `batch/infrastructure/batch_data_loader.py` | JSON/JSONL input loading |
| `config/vendor.py` | All vendor config Pydantic models |

### Provider shared
| File | Role |
|------|------|
| `providers/client_base.py` | Online abstract base class |
| `providers/batch_base.py` | Batch abstract base class + BatchResult/BatchTask |
| `providers/error_wrapper.py` | Vendor error → unified error classification |
| `providers/generation_params.py` | Extract temperature/max_tokens/etc from config |
| `providers/mixins.py` | JSON parsing, error handling reusable mixins |
| `providers/batch_client_factory.py` | Vendor string → batch client factory |

---

## Deep Dives

### Schema Compilation Pipeline

How a YAML schema on disk becomes the vendor-specific format sent to the API.

```
Stage 1: Load                    Stage 2: Unify              Stage 3: Dispatch
                                                              Injection
schema/extraction.yml    ──▶    Unified format:         ──▶  dispatch_task()
  name: extraction               {name, fields: [            calls resolved,
  fields:                          {id, type, required}       results captured
    - id: title                   ]}
      type: string                                      ──▶  Stage 4: Compile
    - id: tags                                                for vendor
      type: array
      items: {type: string}

Stage 4 output per vendor:

  OpenAI/Groq:    {"name":"...","schema":{"type":"object","properties":{...},"required":[...]}}
  Anthropic:      [{"name":"...","input_schema":{"type":"object","properties":{...}}}]  (as tools)
  Gemini:         {"name":"...","schema":{"type":"object","properties":{...}}}  (no additionalProperties)
  Ollama Local:   {"type":"object","properties":{...}}  (flat, title stripped to prevent echo)
  Ollama Cloud:   Schema injected into prompt text (no native support)
  Cohere:         {"type":"object","properties":{...}}  (minimal)
```

Key files: `output/response/schema.py` (orchestrator), `output/response/loader.py` (file discovery), `output/response/vendor_compilation.py` (per-vendor format), `output/response/dispatch_injection.py` (dispatch_task resolution).

---

### Prompt Assembly Pipeline

How a raw prompt template becomes the `messages[]` array sent to the API.

```
Step 1: PromptPreparationService (runs BEFORE builder.py)
  ┌──────────────────────────────────────────────────────┐
  │ Load raw prompt (inline or from prompt_store/*.md)    │
  │ Build field context (upstream outputs, seed data)     │
  │ Apply context_scope (observe/drop/passthrough)        │
  │ Render Jinja2 template ({{ action.field }})           │
  │ Resolve dispatch_task() calls in prompt text          │
  └───────────────────────┬──────────────────────────────┘
                          │ formatted_prompt (string)
                          ▼
Step 2: builder.py
  ┌──────────────────────────────────────────────────────┐
  │ Append observe fields as "Additional context: ..."    │
  │ Compile schema                                        │
  │ Pass to provider client                               │
  └───────────────────────┬──────────────────────────────┘
                          │
                          ▼
Step 3: MessageBuilder.build() — inside each provider client
  ┌──────────────────────────────────────────────────────┐
  │ Look up PROVIDER_MESSAGE_CONFIGS[vendor]              │
  │                                                      │
  │ Assemble body (PromptStyle):                         │
  │   TAGGED        → <|begin_of_user_instruction|> tags │
  │   TAGGED_GROQ   → Groq-specific tag syntax           │
  │   PLAIN_TEXT    → "Instructions: ... Input Text: ..." │
  │   RAW           → empty (Ollama uses roles only)     │
  │                                                      │
  │ Inject schema (SchemaInjection):                     │
  │   NONE          → passed via API param (OpenAI, etc) │
  │   INLINE_FULL   → appended to body (Gemini)          │
  │   INLINE_FIELDS → field names only (Cohere)          │
  │   PROMPT        → prepended to system msg (Ollama)   │
  │                                                      │
  │ Wrap in roles (MessageRole):                         │
  │   SINGLE_USER       → [{role:user, content:body}]    │
  │   SYSTEM_ONLY       → [{role:system, content:prompt},│
  │                        {role:user, content:context}]  │
  │   SYSTEM_PLUS_USER  → [{role:system}, {role:user}]   │
  │                                                      │
  │ Token overflow check (chars/4 heuristic)             │
  └──────────────────────────────────────────────────────┘
```

---

### Error Handling and Recovery

Every error in the LLM module is classified and handled through a layered system.

```
Error Hierarchy:

  AgentActionsError
  ├── ConfigurationError       ← bad config (wrong vendor, missing prompt)
  │   └── ConfigValidationError
  ├── ResourceError
  │   └── DependencyError      ← missing SDK package (pip install anthropic)
  └── ExternalServiceError
      ├── VendorAPIError       ← provider rejected the request
      │   ├── RateLimitError   ← HTTP 429, has retry-after
      │   └── PromptTooLargeError
      └── NetworkError         ← connection/timeout failures


Error Flow:

  SDK Exception (openai.RateLimitError, httpx.TimeoutException, etc.)
       │
       ▼
  wrap_vendor_error()              ← classifies by type or status code
       │
       ├─▶ RateLimitError          → fires RateLimitEvent, retry with backoff
       ├─▶ NetworkError            → fires LLMErrorEvent, retry with backoff
       └─▶ VendorAPIError          → fires LLMErrorEvent, NOT retried


JSON Parse Failures — treated as DATA, not exceptions:

  LLM returns malformed JSON
       │
       ▼
  parse_llm_json()                 ← tries json.loads → fence strip → json_repair
       │ (all fail)
       ▼
  Returns sentinel: [{"raw_response": "...", "_parse_error": "..."}]
       │
       ▼
  Reprompt engine detects _parse_error → sends corrective prompt → retries


Online Retry (per-record):
  RetryService wraps the LLM call
  → Retriable? (NetworkError, RateLimitError) → exponential backoff → retry
  → Non-retriable? → raise immediately
  → Exhausted? → RetryResult(exhausted=True)

Online Reprompt (per-record):
  RepromptService wraps the retry loop
  → Parse error? → build forceful JSON feedback → retry
  → Schema mismatch? → build validation feedback → retry
  → Exhausted? → return last response or raise (configurable)
```

---

### Context Scope: How Input Data is Filtered

```
context_scope controls what the LLM sees:

  ┌─────────────────────────────────────────────┐
  │              Input Record                    │
  │  {name: "Alice", age: 30, ssn: "123-45-6789", │
  │   department: "Engineering", salary: 90000}  │
  └──────────────────────┬──────────────────────┘
                         │
           context_scope: │
             drop: [ssn, salary]
             observe: [department]
             passthrough: [name]
             seed: seed_data/rules.json
                         │
                         ▼
  ┌──────────────────────────────────────────────┐
  │  What the LLM prompt gets:                    │
  │    {name: "Alice", age: 30, department: "Eng"}│
  │    (ssn and salary dropped)                   │
  │                                               │
  │  Appended as "Additional context:":           │
  │    department: Engineering  (observe fields)  │
  │                                               │
  │  Available in Jinja2 templates:               │
  │    {{ seed.rules }}  (seed directive)         │
  └──────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────┐
  │  What the OUTPUT gets:                        │
  │    {<llm_output>, name: "Alice"}              │
  │    (passthrough merged back, LLM wins on     │
  │     collision)                                │
  └──────────────────────────────────────────────┘
```

---

### API Key Flow

```
Config (YAML):                     Runtime:
  model_vendor: openai              agent_config["api_key"] = "OPENAI_API_KEY"
  api_key: OPENAI_API_KEY                    │
                                             ▼
                                    BaseClient.get_api_key()
                                      1. Strip ${} wrapper if present
                                      2. os.getenv("OPENAI_API_KEY")
                                      3. Missing? → ConfigurationError
                                      4. Empty?   → ConfigurationError
                                             │
                                             ▼
                                    Actual key: "sk-abc123..."
                                      → passed to SDK client


Providers that skip key resolution:
  OllamaLocal  → api_key_env_name = "NO_KEY_REQUIRED", invoke() skips get_api_key
  Tool/HITL    → not BaseClient subclasses, no get_api_key call
  AGAC (mock)  → overrides get_api_key() to return "agac-mock-key"

Log safety:
  BaseClient.redact_sensitive_data() → replaces sk-*, sk-ant-*, AIza* patterns
  RedactingFilter (logging) → scrubs all log output before emission
```

---

### Output Pipeline: After the LLM Responds

```
LLM Response
     │
     ▼
JSON Parsing
  parse_llm_json() → json.loads → fence strip → json_repair
  Failure → _parse_error sentinel (data, not exception)
     │
     ▼
Schema Echo Detection
  Did the LLM return the schema definition instead of data?
  (type=object + properties + title = echo)
  Yes → replace with _parse_error sentinel
     │
     ▼
Schema Validation (_validate_llm_output_schema)
  on_schema_mismatch: reject   → SchemaValidationError
  on_schema_mismatch: reprompt → deferred to reprompt loop
  on_schema_mismatch: warn     → log warning, pass through
     │
     ▼
Enrichment Pipeline (UnifiedProcessor)
  ┌─────────────────────────────────────┐
  │ LineageEnricher    → target_id, lineage graph     │
  │ MetadataEnricher   → timestamps, action metadata  │
  │ VersionIdEnricher  → version_correlation_id       │
  │ PassthroughEnricher → merge passthrough fields     │
  │ RequiredFieldsEnricher → ensure required fields    │
  │ RecoveryEnricher   → retry/reprompt metadata       │
  └─────────────────────────────────────┘
     │
     ▼
RecordEnvelope.build()
  Wraps each record:
  {
    content: {action_name: {<llm_output>}},    ← namespaced
    source_guid: "...",                         ← stable identity
    _state: "PROCESSED",                        ← lifecycle
    _state_history: [...],                      ← audit trail
    lineage: {...},
    metadata: {...}
  }
     │
     ▼
ResultCollector → Dispositions
  SUCCESS   → write to target, DISPOSITION_SUCCESS
  FAILED    → tombstone record, DISPOSITION_FAILED
  EXHAUSTED → tombstone record, DISPOSITION_EXHAUSTED
  FILTERED  → no output, DISPOSITION_FILTERED
     │
     ▼
FileWriter.write_target()
  1. SQLite storage backend (authoritative)
  2. JSON file on disk (agent_io/target/{action}/)
```

---

### HITL (Human-in-the-Loop) Deep Dive

Not an LLM at all — a Flask server that blocks until a human approves/rejects.

```
HitlClient.invoke()
     │
     ├─ Find available port (tries 5 sequential ports)
     ├─ Launch Flask server in daemon thread
     ├─ Print URL to terminal
     └─ Block on threading.Event.wait(timeout)
            │
            ▼
     ┌──────────────────────────────────────────┐
     │          Flask Server Routes              │
     │                                           │
     │  GET  /              → approval UI (HTML) │
     │  GET  /api/context   → record data + fields│
     │  GET  /api/review-state → review progress  │
     │  POST /api/review-record → per-record decision│
     │  POST /api/approve   → approve (single)    │
     │  POST /api/reject    → reject (single)     │
     │  POST /api/submit    → submit all reviews  │
     │  POST /api/shutdown  → manual shutdown      │
     └──────────────────────────────────────────┘

Security:
  - Loopback-only bind (127.0.0.1) — no remote access
  - CSP headers with per-request nonce
  - Cache-Control: no-store on every response
  Note: the UI is a single-user local tool; loopback is the trust boundary.

State persistence:
  Reviews saved to .hitl_reviews_{hash}.json after each decision
  On restart: validates record count + data fingerprint (SHA-256)
  Stale state (different data) is discarded

Timeout:
  No response within timeout → hitl_status: "timeout"
  Partial reviews are persisted → next run resumes where left off
```

---

### Provider Comparison Matrix

| | OpenAI | Anthropic | Gemini | Groq | Cohere | Ollama Local | Ollama Cloud |
|---|---|---|---|---|---|---|---|
| **JSON mode** | `response_format: json_schema` | Schema as `tools` param | `response_mime_type: application/json` | Same as OpenAI | `response_format: {type: json_object, schema}` | `format` param | Schema in prompt text |
| **max_tokens rename** | (unchanged) | (unchanged, default 4096) | `max_output_tokens` | (unchanged) | (unchanged) | `num_predict` | `num_predict` |
| **stop rename** | (unchanged) | `stop_sequences` | `stop_sequences` | (unchanged) | `stop_sequences` | (list-coerced) | (list-coerced) |
| **Error strategy** | Type-based | Type-based | Status-code | Type-based | Status-code | Status-code | Status-code |
| **retry-after** | Yes | Yes | No | Yes | No | No | No |
| **Batch support** | Native API | Message Batches API | Batch Prediction | Native API | None | Simulated (threads) | Simulated (threads) |
| **Unique** | Reference impl | Prompt caching, tool-use | — | — | `top_p`→`p` | No API key, schema echo prevention | No structured output |

---

### Events and Observability

```
Events fired during an LLM call:

  ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
  │ L001        │     │ SDK Call     │     │ L002         │
  │ LLMRequest  │────▶│              │────▶│ LLMResponse  │
  │ Event       │     │              │     │ Event        │
  └─────────────┘     └──────┬───────┘     └──────────────┘
                             │
                     (on failure)
                             │
                      ┌──────▼───────┐
                      │ L003/L004    │
                      │ Error or     │
                      │ RateLimit    │
                      │ Event        │
                      └──────────────┘

Batch events:
  B001 BatchSubmitted    → after provider accepts the batch
  B002 BatchProgress     → during polling loop
  B003 BatchComplete     → all results processed
  B009 SubmissionFailed  → provider rejected submission
  B012 PartialFailure   → some records failed

Usage tracking per provider:
  OpenAI/Groq:  response.usage.prompt_tokens / completion_tokens
  Anthropic:    response.usage.input_tokens / output_tokens
  Gemini:       response.usage_metadata.prompt_token_count
  Cohere:       response.usage.tokens.input_tokens
  Ollama:       response.prompt_eval_count / eval_count

  Stored in ContextVar (async-safe) via set_last_usage()

Logging levels:
  DEBUG   → successful parse, internal state, cleanup
  INFO    → batch submitted/complete, retry success, LLM call elapsed time
  WARNING → malformed JSON, recoverable failures, empty responses
  ERROR   → unrecoverable failures, state corruption
```

---

### Batch Infrastructure: Persistent State

```
{output_dir}/batch/
  │
  ├── .batch_registry.json          ← all batch jobs, status, provider
  │     {file_name: {batch_id, status, provider, parent_file_name, ...}}
  │     Thread-safe (Lock), atomic writes (temp+fsync+rename)
  │     Idempotent: re-submit same batch → returns existing batch_id
  │
  ├── .context_map_{batch_name}     ← per-record input data + metadata
  │     {custom_id: {original_data, _batch_filter_status, _passthrough_fields}}
  │     Written at submission, read at result processing
  │
  ├── .recovery_state_{name}.json   ← retry/reprompt state machine
  │     {phase, retry_attempt, missing_ids, graduated_results, ...}
  │     Survives crashes — each run picks up where the last left off
  │     Deleted after successful finalization
  │
  ├── .batch_carry_forward.json     ← GUIDs with terminal dispositions
  │     Merged back into output at finalization
  │
  ├── {name}_batch_input.jsonl      ← tasks sent to provider
  └── {batch_id}_results.jsonl      ← raw results from provider

All state files use atomic_json_write():
  tempfile.mkstemp → json.dump → flush → fsync → atomic rename
  On failure: temp file unlinked, original untouched
```
