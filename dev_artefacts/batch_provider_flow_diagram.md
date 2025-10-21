# Batch Provider Flow - Visual Diagram

**What Happens When Adding a New Vendor**

---

## The Complete Journey

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: USER CREATES WORKFLOW CONFIG                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   workflow.yaml:                                                             │
│   ┌────────────────────────────────────────┐                                │
│   │ workflow_id: my_workflow               │                                │
│   │ agents:                                │                                │
│   │   fact_extractor:                      │                                │
│   │     model_vendor: gemini  ← NEW VENDOR │                                │
│   │     model_name: gemini-1.5-flash       │                                │
│   │     schema_name: FactExtraction        │                                │
│   └────────────────────────────────────────┘                                │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: CLI ROUTES TO WORKFLOW ENGINE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   $ python -m agent_actions.cli.main workflow run workflow.yaml             │
│                                                                              │
│   cli/main.py → workflow/engine.py → tasks/services/batch_service.py        │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: BATCH SERVICE NEEDS A PROVIDER                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   batch_service.py:                                                          │
│   ┌────────────────────────────────────────────────────┐                    │
│   │ def _get_provider_for_config(agent_config):        │                    │
│   │     vendor = agent_config['model_vendor']          │                    │
│   │     # vendor = "gemini"                            │                    │
│   │                                                     │                    │
│   │     return create_batch_provider(vendor, **kwargs) │                    │
│   └─────────────────────┬──────────────────────────────┘                    │
│                         │                                                    │
└─────────────────────────┼────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: FACTORY CREATES PROVIDER INSTANCE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   factory.py:                                                                │
│   ┌─────────────────────────────────────────────────────────┐               │
│   │ def create_batch_provider(provider_type, **kwargs):     │               │
│   │     if provider_type == 'openai':                       │               │
│   │         return OpenAIBatchProvider(**kwargs)            │               │
│   │     elif provider_type == 'anthropic':                  │               │
│   │         return AnthropicBatchProvider(**kwargs)         │               │
│   │     elif provider_type == 'ollama':                     │               │
│   │         return OllamaLocalBatchProvider(**kwargs)       │               │
│   │     elif provider_type == 'gemini':  ← YOU ADD THIS    │               │
│   │         return GeminiBatchProvider(**kwargs)            │               │
│   └──────────────────────────┬──────────────────────────────┘               │
│                              │                                               │
└──────────────────────────────┼───────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: PROVIDER INSTANCE CREATED                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   gemini/provider.py:                                                        │
│   ┌───────────────────────────────────────────────┐                         │
│   │ class GeminiBatchProvider(BatchProvider):     │                         │
│   │     def __init__(self, api_key=None):         │                         │
│   │         import google.generativeai as genai   │                         │
│   │         genai.configure(api_key=api_key)      │                         │
│   │         self.genai = genai                    │                         │
│   └───────────────────────────────────────────────┘                         │
│                                                                              │
│   ✅ Provider ready to use!                                                 │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: BATCH SERVICE CALLS prepare_tasks()                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   batch_service.py:                                                          │
│   ┌────────────────────────────────────────────────────┐                    │
│   │ # Load input data                                  │                    │
│   │ data = [                                           │                    │
│   │   {"target_id": "1", "content": "text..."},       │                    │
│   │   {"target_id": "2", "content": "text..."}        │                    │
│   │ ]                                                  │                    │
│   │                                                    │                    │
│   │ # Compile schema                                  │                    │
│   │ schema = compile_schema(agent_config)             │                    │
│   │                                                    │                    │
│   │ # Provider transforms data                        │                    │
│   │ tasks = provider.prepare_tasks(data, agent_config)│                    │
│   └─────────────────────┬──────────────────────────────┘                    │
│                         │                                                    │
└─────────────────────────┼────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: YOUR prepare_tasks() TRANSFORMS DATA                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   YOUR CODE in gemini/provider.py:                                          │
│   ┌──────────────────────────────────────────────────────────┐              │
│   │ def prepare_tasks(self, data, agent_config):             │              │
│   │     tasks = []                                           │              │
│   │     json_mode = agent_config.get("json_mode", True)     │              │
│   │     schema = agent_config.get("compiled_schema") \      │              │
│   │              if json_mode else None                     │              │
│   │                                                          │              │
│   │     for row in data:                                    │              │
│   │         batch_task = BatchTask(                         │              │
│   │             custom_id=row["target_id"],                 │              │
│   │             prompt=agent_config["prompt"],              │              │
│   │             user_content=json.dumps(row["content"]),    │              │
│   │             model_config={...}                          │              │
│   │         )                                               │              │
│   │         gemini_task = self.format_task_for_provider(    │              │
│   │             batch_task, schema                          │              │
│   │         )                                               │              │
│   │         tasks.append(gemini_task)                       │              │
│   │                                                          │              │
│   │     return tasks  # Gemini-specific format              │              │
│   └──────────────────────────┬───────────────────────────────┘              │
│                              │                                               │
└──────────────────────────────┼───────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 8: YOUR format_task_for_provider() CONVERTS EACH TASK                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Input (standardized):           Output (Gemini-specific):                 │
│   ┌──────────────────────┐        ┌────────────────────────────┐            │
│   │ BatchTask:           │        │ {                          │            │
│   │   custom_id: "1"     │   →    │   "custom_id": "1",        │            │
│   │   prompt: "Extract"  │        │   "request": {             │            │
│   │   user_content: "{}" │        │     "model": "gemini-...", │            │
│   │   model_config: {}   │        │     "contents": [{         │            │
│   │   schema: {...}      │        │       "role": "user",      │            │
│   └──────────────────────┘        │       "parts": [...]       │            │
│                                   │     }],                    │            │
│                                   │     "generationConfig": {  │            │
│                                   │       "response_schema": {}│            │
│                                   │     }                      │            │
│                                   │   }                        │            │
│                                   │ }                          │            │
│                                   └────────────────────────────┘            │
│                                                                              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 9: BATCH SERVICE CALLS submit_batch()                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   batch_service.py:                                                          │
│   ┌────────────────────────────────────────────────────┐                    │
│   │ batch_id = provider.submit_batch(                  │                    │
│   │     tasks=tasks,                                   │                    │
│   │     batch_name="workflow_fact_extractor.json",     │                    │
│   │     output_directory="output/"                     │                    │
│   │ )                                                  │                    │
│   └─────────────────────┬──────────────────────────────┘                    │
│                         │                                                    │
└─────────────────────────┼────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 10: YOUR submit_batch() SENDS TO VENDOR                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   YOUR CODE:                                                                 │
│   ┌──────────────────────────────────────────────────────────┐              │
│   │ def submit_batch(self, tasks, batch_name, output_dir):  │              │
│   │     # ✅ OUR CODE: Use base helper                      │              │
│   │     batch_dir = self._get_batch_directory(output_dir)   │              │
│   │     file_path = self._write_jsonl_file(                 │              │
│   │         tasks, batch_dir, batch_name, "gemini"          │              │
│   │     )                                                    │              │
│   │                                                          │              │
│   │     # ❌ VENDOR CODE: Call Gemini API                   │              │
│   │     batch_job = self.genai.batch_create(                │              │
│   │         requests=tasks,                                 │              │
│   │         name=batch_name                                 │              │
│   │     )                                                    │              │
│   │                                                          │              │
│   │     return batch_job.id  # e.g., "gemini_batch_abc123"  │              │
│   └──────────────────────────────────────────────────────────┘              │
│                                                                              │
│   Files created:                                                             │
│   📁 output/batch/workflow_fact_extractor_gemini_batch_input.jsonl          │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 11: BATCH SERVICE SAVES TO REGISTRY                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   batch_service.py (automatic, you don't write this!):                      │
│   ┌──────────────────────────────────────────────────────────┐              │
│   │ self._save_batch_job_id(                                │              │
│   │     batch_id="gemini_batch_abc123",                     │              │
│   │     output_directory="output/",                         │              │
│   │     file_name="workflow_fact_extractor.json",           │              │
│   │     provider_type="gemini",                             │              │
│   │     record_count=2                                      │              │
│   │ )                                                        │              │
│   └──────────────────────────────────────────────────────────┘              │
│                                                                              │
│   Files created:                                                             │
│   📁 output/batch/.batch_registry.json:                                     │
│   ┌─────────────────────────────────────────────────┐                       │
│   │ {                                               │                       │
│   │   "workflow_fact_extractor.json": {             │                       │
│   │     "batch_id": "gemini_batch_abc123",          │                       │
│   │     "status": "submitted",                      │                       │
│   │     "timestamp": "2025-10-20T...",              │                       │
│   │     "provider": "gemini",                       │                       │
│   │     "record_count": 2                           │                       │
│   │   }                                             │                       │
│   │ }                                               │                       │
│   └─────────────────────────────────────────────────┘                       │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 12: USER RUNS WORKFLOW AGAIN (TO CHECK STATUS)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   $ python -m agent_actions.cli.main workflow run workflow.yaml             │
│                                                                              │
│   batch_service.py:                                                          │
│   ┌────────────────────────────────────────────────────┐                    │
│   │ # Check registry for existing batch                │                    │
│   │ existing_batch = self._check_for_existing_batch()  │                    │
│   │ # Found: gemini_batch_abc123                       │                    │
│   │                                                     │                    │
│   │ # Check status with provider                       │                    │
│   │ status = provider.check_status(batch_id)           │                    │
│   └─────────────────────┬──────────────────────────────┘                    │
│                         │                                                    │
└─────────────────────────┼────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 13: YOUR check_status() POLLS VENDOR                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   YOUR CODE:                                                                 │
│   ┌──────────────────────────────────────────────────────────┐              │
│   │ def check_status(self, batch_id):                       │              │
│   │     # ❌ VENDOR CODE: Call Gemini API                   │              │
│   │     batch_info = self.genai.batch_get(batch_id)         │              │
│   │                                                          │              │
│   │     # ✅ OUR CODE: Map to standard status               │              │
│   │     status_mapping = {                                  │              │
│   │         'PENDING': 'validating',                        │              │
│   │         'RUNNING': 'in_progress',                       │              │
│   │         'COMPLETED': 'completed',                       │              │
│   │         'FAILED': 'failed'                              │              │
│   │     }                                                    │              │
│   │                                                          │              │
│   │     gemini_status = batch_info.state                    │              │
│   │     return status_mapping.get(gemini_status)            │              │
│   └──────────────────────────────────────────────────────────┘              │
│                                                                              │
│   Status progression:                                                        │
│   submitted → validating → in_progress → completed ✅                       │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 14: BATCH SERVICE CALLS retrieve_results()                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   batch_service.py:                                                          │
│   ┌────────────────────────────────────────────────────┐                    │
│   │ if status == 'completed':                          │                    │
│   │     results = provider.retrieve_results(           │                    │
│   │         batch_id="gemini_batch_abc123",            │                    │
│   │         output_directory="output/"                 │                    │
│   │     )                                              │                    │
│   │     # results = [BatchResult, BatchResult, ...]    │                    │
│   └─────────────────────┬──────────────────────────────┘                    │
│                         │                                                    │
└─────────────────────────┼────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 15: YOUR retrieve_results() DOWNLOADS AND PARSES                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   YOUR CODE:                                                                 │
│   ┌──────────────────────────────────────────────────────────┐              │
│   │ def retrieve_results(self, batch_id, output_dir):       │              │
│   │     # ❌ VENDOR CODE: Download from Gemini              │              │
│   │     results_data = self.genai.batch_get_results(        │              │
│   │         batch_id                                        │              │
│   │     )                                                    │              │
│   │                                                          │              │
│   │     # ✅ OUR CODE: Save locally (optional)              │              │
│   │     if output_dir:                                      │              │
│   │         batch_dir = self._get_batch_directory(...)      │              │
│   │         # Save raw results...                           │              │
│   │                                                          │              │
│   │     # ✅ OUR CODE: Parse to BatchResult                 │              │
│   │     batch_results = []                                  │              │
│   │     for raw in results_data:                            │              │
│   │         result = self.parse_provider_response(raw)      │              │
│   │         batch_results.append(result)                    │              │
│   │                                                          │              │
│   │     return batch_results                                │              │
│   └──────────────────────────────────────────────────────────┘              │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 16: YOUR parse_provider_response() STANDARDIZES FORMAT                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Input (Gemini-specific):       Output (standardized):                     │
│   ┌────────────────────────┐     ┌──────────────────────────┐               │
│   │ {                      │     │ BatchResult(             │               │
│   │   "custom_id": "1",    │     │   custom_id="1",         │               │
│   │   "response": {        │  →  │   content={...},         │               │
│   │     "candidates": [{   │     │   success=True,          │               │
│   │       "content": {     │     │   error=None,            │               │
│   │         "parts": [     │     │   metadata={...},        │               │
│   │           {"text": ""}│     │   usage={...}            │               │
│   │         ]              │     │ )                        │               │
│   │       }                │     └──────────────────────────┘               │
│   │     }]                 │                                                │
│   │   }                    │                                                │
│   │ }                      │                                                │
│   └────────────────────────┘                                                │
│                                                                              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 17: BATCH SERVICE PROCESSES RESULTS (100% SHARED CODE)                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   batch_service.py (automatic, you don't write this!):                      │
│   ┌──────────────────────────────────────────────────────────┐              │
│   │ # Extract successful and failed results                 │              │
│   │ successful = [r for r in results if r.success]          │              │
│   │ failed = [r for r in results if not r.success]          │              │
│   │                                                          │              │
│   │ # Save successful results to agent_io/                  │              │
│   │ self._write_batch_results(successful, ...)              │              │
│   │                                                          │              │
│   │ # Create retry batch if failures exist                  │              │
│   │ if failed and retry_count < max_retries:                │              │
│   │     retry_batch_id = provider.submit_batch(             │              │
│   │         failed_tasks, "workflow_retry_1.json", ...      │              │
│   │     )                                                    │              │
│   │                                                          │              │
│   │ # Move to DLQ if max retries exceeded                   │              │
│   │ if failed and retry_count >= max_retries:               │              │
│   │     self._write_to_dlq(failed, ...)                     │              │
│   │                                                          │              │
│   │ # Update manifest                                       │              │
│   │ self._update_manifest(batch_id, results, ...)           │              │
│   │                                                          │              │
│   │ # Handle observe fields (lineage tracking)              │              │
│   │ self._track_lineage(results, ...)                       │              │
│   └──────────────────────────────────────────────────────────┘              │
│                                                                              │
│   Files created:                                                             │
│   📁 output/agent_io/fact_extractor/target/1.json                           │
│   📁 output/agent_io/fact_extractor/target/2.json                           │
│   📁 output/manifest.json                                                   │
│   📁 output/batch/dead_letter_queue.jsonl (if max retries hit)              │
│                                                                              │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 18: WORKFLOW CONTINUES TO NEXT AGENT (IF ANY)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   workflow/engine.py:                                                        │
│   ┌────────────────────────────────────────────────────┐                    │
│   │ # fact_extractor complete, run next agent...       │                    │
│   │ next_agent = workflow['agents']['summarizer']      │                    │
│   │ next_agent['model_vendor'] = 'gemini'  ← WORKS!    │                    │
│   └────────────────────────────────────────────────────┘                    │
│                                                                              │
│   ✅ Same provider works for all agents in workflow!                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                                   ▼

┌─────────────────────────────────────────────────────────────────────────────┐
│ COMPLETE! ✅                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  What YOU implemented:                                                       │
│  ✅ 6 methods in gemini/provider.py (~150 lines)                            │
│  ✅ Factory registration (2 lines)                                          │
│                                                                              │
│  What you got FOR FREE:                                                      │
│  ✅ Registry management                                                     │
│  ✅ Retry logic                                                             │
│  ✅ DLQ                                                                     │
│  ✅ Manifests                                                               │
│  ✅ Validation                                                              │
│  ✅ output_field handling                                                   │
│  ✅ Lineage tracking                                                        │
│  ✅ WHERE clause filtering                                                  │
│  ✅ Passthrough data                                                        │
│  ✅ Multi-agent workflows                                                   │
│                                                                              │
│  Total effort: ~2-3 hours                                                    │
│  Total benefit: 100% batch system integration 🎉                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Takeaways

### 🎯 You Only Touch 3 Files
1. `gemini/provider.py` - Implement 6 methods
2. `gemini/__init__.py` - Export provider class
3. `factory.py` - Register provider (2 lines)

### 🎁 Everything Else Is Provided
- Registry tracking
- Retry mechanism
- Error handling (DLQ)
- Manifest generation
- Schema validation
- File management

### 🔄 The Magic Loop

```
User Config → Factory → Your Provider → Vendor API
                ↓
         BatchResult (standardized)
                ↓
         BatchService (100% shared!)
                ↓
         Registry, Retry, DLQ, Manifests
```

### ⚡ The Power of Abstraction

**Before (without abstraction):**
- Each vendor: 1000+ lines of code
- Retry logic: duplicated 4 times
- DLQ: duplicated 4 times
- Registry: duplicated 4 times
- Total: ~4000 lines of duplicated code

**After (with abstraction):**
- Each vendor: ~150 lines (just 6 methods)
- Retry logic: 1 implementation (BatchService)
- DLQ: 1 implementation (BatchService)
- Registry: 1 implementation (BatchService)
- Total: ~600 lines + shared BatchService

**Result: 85% less code, 100% more maintainable!** 🚀
