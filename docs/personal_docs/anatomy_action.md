
⏺ Here's the anatomy of an action - a complete data flow summary:

  Action Anatomy: Context, Prompt, and Schema

  1. CONTEXT - Where does an action get its data?

  Entry Point: ContextScopeProcessor.build_field_context_with_history() at context_scope_processor.py:305
  ┌────────────┬──────────────────────────────────┬────────────────────────────────────────────────┐
  │ Namespace  │              Source              │                  Description                   │
  ├────────────┼──────────────────────────────────┼────────────────────────────────────────────────┤
  │ source     │ Input record's content portion   │ Original document/data being processed         │
  ├────────────┼──────────────────────────────────┼────────────────────────────────────────────────┤
  │ {dep_name} │ Historical artifacts OR contents │ Fields from upstream dependency actions        │
  ├────────────┼──────────────────────────────────┼────────────────────────────────────────────────┤
  │ seed       │ seed_data/*.json files           │ Static reference data (exam syllabi, configs)  │
  ├────────────┼──────────────────────────────────┼────────────────────────────────────────────────┤
  │ loop       │ Workflow executor                │ Loop iteration info (loop.index, loop.count)   │
  ├────────────┼──────────────────────────────────┼────────────────────────────────────────────────┤
  │ workflow   │ Workflow executor                │ Workflow metadata (workflow.id, workflow.name) │
  └────────────┴──────────────────────────────────┴────────────────────────────────────────────────┘
  Context Scope Directives (applied at context_scope_processor.py:145):
  - observe: Fields visible to LLM (extracted to llm_context)
  - passthrough: Fields copied to output (also visible to LLM)
  - drop: Fields removed from context (security)

  field_context → apply_context_scope() → prompt_context (for templates)
                                        → llm_context (for LLM)
                                        → passthrough_fields (for output)

  ---
  2. PROMPT - Where does the template come from?

  Entry Point: PromptFormatter.get_raw_prompt() at prompt_formatter.py:14
  ┌───────────────┬────────────────────────────────────────┬────────────────────────────────────────────┐
  │    Format     │                Example                 │                 Resolution                 │
  ├───────────────┼────────────────────────────────────────┼────────────────────────────────────────────┤
  │ Inline string │ prompt: "Summarize: {{ source.text }}" │ Used directly                              │
  ├───────────────┼────────────────────────────────────────┼────────────────────────────────────────────┤
  │ External ref  │ prompt: $workflow_name.Prompt_Key      │ Loaded from *.md files                     │
  ├───────────────┼────────────────────────────────────────┼────────────────────────────────────────────┤
  │ Default       │ (no prompt field)                      │ "Process the following content: {content}" │
  └───────────────┴────────────────────────────────────────┴────────────────────────────────────────────┘
  External Prompt Format (in .md files):
  {prompt Summarize_Content}
  Summarize the following text...
  {{ source.text }}
  {end_prompt}

  Template Rendering (prompt_preparation_service.py:343):
  1. Pre-flight validation - check all {{ vars }} exist
  2. Jinja2 rendering - substitute {{ action.field }} with values from prompt_context
  3. Function injection - inject llm_context JSON into dispatch calls

  ---
  3. SCHEMA - Where does output structure come from?

  Entry Point: SchemaExtractor.extract_schema() at schema_extractor.py:100
  ┌────────────────┬──────────┬───────────────────────────────────────────────┐
  │     Source     │ Priority │                   Location                    │
  ├────────────────┼──────────┼───────────────────────────────────────────────┤
  │ Inline dict    │ 1        │ schema: {type: object, properties: {...}}     │
  ├────────────────┼──────────┼───────────────────────────────────────────────┤
  │ Inline list    │ 1        │ schema: [{id: field1, type: string}]          │
  ├────────────────┼──────────┼───────────────────────────────────────────────┤
  │ External file  │ 2        │ schema_name: my_schema → schema/my_schema.yml │
  ├────────────────┼──────────┼───────────────────────────────────────────────┤
  │ UDF decorators │ 3        │ @output_schema on Python function             │
  ├────────────────┼──────────┼───────────────────────────────────────────────┤
  │ UDF registry   │ 4        │ Legacy UDF_REGISTRY lookup                    │
  └────────────────┴──────────┴───────────────────────────────────────────────┘
  Tool Actions (NEW REQUIREMENT):
  - Must have both input_schema and output_schema defined
  - Validation enforced at workflow_static_analyzer.py:145 (_check_tool_schemas())

  ---
  4. Complete Data Flow Diagram

  ┌─────────────────────────────────────────────────────────────────┐
  │                     RecordProcessor.process()                    │
  └─────────────────────────────────────────────────────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          │                                               │
          ▼                                               ▼
  ┌───────────────────┐                      ┌───────────────────────┐
  │  1. BUILD CONTEXT │                      │  2. LOAD PROMPT       │
  │                   │                      │                       │
  │  • source content │                      │  • Inline OR external │
  │  • dep history    │                      │  • From .md files     │
  │  • seed data      │                      │                       │
  └─────────┬─────────┘                      └───────────┬───────────┘
            │                                            │
            └────────────────────┬───────────────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────┐
                │   3. APPLY CONTEXT_SCOPE       │
                │                                │
                │   observe → llm_context        │
                │   passthrough → output fields  │
                │   drop → removed               │
                └────────────────┬───────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────┐
                │   4. RENDER TEMPLATE           │
                │                                │
                │   {{ action.field }} → values  │
                │   Jinja2 substitution          │
                └────────────────┬───────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────┐
                │   5. EXECUTE LLM/TOOL          │
                │                                │
                │   formatted_prompt + schema    │
                │   → LLM response               │
                └────────────────┬───────────────┘
                                 │
                                 ▼
                ┌────────────────────────────────┐
                │   6. TRANSFORM OUTPUT          │
                │                                │
                │   • Validate against schema    │
                │   • Merge passthrough fields   │
                │   • Add lineage metadata       │
                └────────────────────────────────┘
