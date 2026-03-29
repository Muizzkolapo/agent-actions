# Launch Video Script — Agent Actions

**Runtime target**: 4–5 minutes
**Format**: Screen recording with voiceover
**Demo**: `examples/review_analyzer` (15 product reviews, 6 actions, 3 vendors)

---

## SCENE 1: What Is This (0:00–0:30)

**SHOW**: Terminal. `tree examples/review_analyzer` — show the project structure briefly. Then open `review_analyzer.yml` in editor.

**VOICEOVER**:

> Agent Actions is a declarative framework for multi-step LLM workflows. You define actions in YAML. Each action gets its own model, its own context window, its own schema, and its own pre-check gate.
>
> This is a review analyzer. 15 product reviews go in. Extracted claims, quality scores, merchant responses, and product insights come out. Six actions. Three different model vendors. Let me walk through it.

---

## SCENE 2: The Workflow — Top to Bottom (0:30–1:15)

**SHOW**: Scroll slowly through `review_analyzer.yml`, pausing on each action.

**VOICEOVER** (as you scroll past each action):

> First action — extract claims. Uses Groq's Llama 3.3 for extraction. It's cheap and fast — extraction doesn't need expensive reasoning. The LLM sees the review text and product name. It does not see the star rating — that's deliberately dropped so it doesn't anchor the analysis.

**SHOW**: Highlight `model_vendor: groq` and the `drop: - source.star_rating` lines.

> Second action — score quality. Three independent scorers running in parallel.

**SHOW**: Highlight the `versions:` block.

> Two lines of YAML. Three parallel LLM calls. Each scorer sees the extracted claims and the rubric, but never each other's scores. That's context isolation — biased reviewers make a useless pipeline.

> Third — aggregate scores. This is a tool action, not an LLM. Python function. Deterministic. Math doesn't hallucinate.

**SHOW**: Highlight `kind: tool` and `impl: aggregate_quality_scores`.

> Fourth — generate merchant response. This one uses Anthropic Claude — better reasoning for empathetic, nuanced replies. And it has a guard.

**SHOW**: Highlight the `guard:` block.

> If the review scored below 6, the LLM never fires. No tokens burned. No latency spent. Across a batch of 10,000 reviews, this guard alone can cut thousands of unnecessary LLM calls.

> Fifth — extract product insights. Runs in parallel with the response generation. Same guard — skip junk reviews.

> Sixth — format output. Another tool action. Packages everything into the final structure.

---

## SCENE 3: Context Scoping — What Each Action Thinks About (1:15–2:00)

**SHOW**: Scroll back to `generate_response`. Highlight the full `context_scope:` block.

**VOICEOVER**:

> This is what makes Agent Actions different from chaining API calls. Context scoping.

> Observe — these fields go into the LLM prompt. The response generator sees the review text, the extracted claims, the consensus score, the strengths and weaknesses. That's it.

**SHOW**: Highlight `drop: - score_quality.*`

> Drop — the response generator does not see individual scorer reasoning. Three scorers produced detailed analysis. None of that reaches this action. Clean context, better output.

**SHOW**: Highlight `passthrough:` lines.

> Passthrough — review ID, reviewer name, product name flow straight to the output. Zero tokens. The LLM never sees them, but they show up in the final record.

> Every action controls what it thinks about. Smaller prompts. Fewer tokens. Less confusion. Better results.

---

## SCENE 4: Schema Validation + Reprompting (2:00–2:30)

**SHOW**: Open `schema/review_analyzer/score_quality.yml` in split view.

**VOICEOVER**:

> Every action has a schema. This one defines what the quality scorer must return — helpfulness score, specificity score, authenticity score, overall score, reasoning, and red flags.

**SHOW**: Highlight `required:` section.

> If the LLM returns something that doesn't match — missing field, wrong type — the framework catches it. And instead of failing, it reprompts. Feeds the validation error back to the LLM: "you missed the authenticity_score field, here's what you returned, try again." Configurable attempts. Configurable behavior on exhaustion.

**SHOW**: Scroll back to YAML, highlight the `retry:` block on `extract_claims`.

> Transport failures get retried too. Retry is for network errors. Reprompt is for bad output. Different problems, different recovery.

---

## SCENE 5: Multi-Vendor + Parallel Consensus (2:30–3:10)

**SHOW**: Scroll through the YAML, highlight the three different `model_vendor` lines across actions.

**VOICEOVER**:

> Three vendors in one workflow. Groq for cheap extraction. OpenAI for scoring. Anthropic for response generation. Each action picks the model that fits its job. Switching a vendor is one line.

**SHOW**: Highlight the `versions:` and `version_consumption:` blocks together.

> The parallel consensus pattern. Three scorers evaluate every review independently. The aggregate action merges them with weighted voting. Two declarations — `versions` and `version_consumption` — that's it. In a code-based pipeline, that's three HTTP calls, a custom merge function, manual wiring, and error handling for each branch.

---

## SCENE 6: Seed Data + Prompt Store (3:10–3:40)

**SHOW**: Open `seed_data/evaluation_rubric.json` briefly.

**VOICEOVER**:

> The scoring rubric isn't hardcoded in prompts. It's seed data — a JSON file that gets injected at runtime. Change the rubric, the whole pipeline adapts. No prompt rewrites.

**SHOW**: Open `prompt_store/review_analyzer.md`. Scroll to `{prompt Score_Quality}`.

> Prompts live in markdown files with Jinja2 templates. This scorer prompt references the rubric dynamically — `seed_data.rubric.scoring_criteria`. The prompt, the schema, and the context scope all compose. Each one does its job.

**SHOW**: Highlight `{{ seed_data.rubric.scoring_criteria | tojson }}` and the `{% if version.first %}` block.

> And each scorer gets a different role. First one focuses on helpfulness. Last one focuses on authenticity. Middle one is balanced. Same prompt template, different behavior per version.

---

## SCENE 7: Running It (3:40–4:15)

**SHOW**: Terminal.

**TYPE**:
```bash
agac run -a review_analyzer
```

**VOICEOVER**:

> One command. The framework resolves the dependency graph, runs actions in topological order, parallelizes where it can, evaluates guards per record, validates every output against its schema, and writes results to the target directory.

**SHOW**: Let the output scroll. Highlight key log lines — action start/complete, guard filters, batch progress.

> 15 reviews. The guard filters out the low-quality ones before they reach the response generator. The bot review — R015 — never gets a merchant response. Never gets product insights extracted. Tokens saved.

**SHOW**: Open `agent_io/target/` and show the output files briefly.

> Structured output. Every record. Every action. Traceable.

**TYPE**:
```bash
agac inspect dependencies -a review_analyzer
```

**SHOW**: The dependency graph output.

> And you can inspect the full dependency graph, trace context flow per action, or preview what any action will see before running it.

---

## SCENE 8: Batch Mode (4:15–4:30)

**SHOW**: Scroll to `defaults:` in the YAML. Highlight `run_mode: batch`.

**VOICEOVER**:

> Same workflow, batch mode. One line change. The framework submits to provider batch APIs — 50% cost savings on OpenAI and Anthropic. Handles submission, polling, result retrieval, and retry chains automatically.

---

## SCENE 9: Close (4:30–4:50)

**SHOW**: Full `review_analyzer.yml` scrolling through one last time.

**VOICEOVER**:

> Six actions. Three vendors. Parallel consensus. Guards. Context scoping. Schema validation. Seed data injection. Batch processing. All declared in one YAML file.
>
> Agent Actions. Define workflows in YAML — each action gets its own model, context window, schema, and pre-check gate.
>
> Open source. MIT license. pip install agent-actions.

**SHOW**: Terminal.

**TYPE**:
```bash
pip install agent-actions
agac init my-project
```

---

## RECORDING NOTES

**Terminal setup**:
- Font size 16+ for readability
- Dark theme (Dracula or similar)
- Working directory: `examples/review_analyzer`
- Editor: VS Code or Cursor with YAML syntax highlighting

**Files to have open / switch between**:
1. `agent_config/review_analyzer.yml` — the star, on screen 70% of the time
2. `schema/review_analyzer/score_quality.yml` — brief cutaway in Scene 4
3. `seed_data/evaluation_rubric.json` — brief cutaway in Scene 6
4. `prompt_store/review_analyzer.md` — brief cutaway in Scene 6
5. Terminal — for Scenes 7 and 9

**Pacing**:
- Scroll slowly through YAML — give the viewer time to read
- Hold 2-3 seconds on each highlighted block
- When typing commands, type at readable speed, not full speed

**Feature checklist (make sure every one gets a moment)**:
- [x] Multi-vendor model selection (Scene 2, 5)
- [x] Context scoping — observe, drop, passthrough (Scene 3)
- [x] Guards as cost control (Scene 2)
- [x] Schema validation + reprompting (Scene 4)
- [x] Parallel consensus / versions (Scene 2, 5)
- [x] Tool actions / UDFs (Scene 2)
- [x] Seed data injection (Scene 6)
- [x] Prompt store with Jinja2 (Scene 6)
- [x] Batch processing (Scene 8)
- [x] Dependency graph / inspect tooling (Scene 7)
- [x] Retry vs reprompt distinction (Scene 4)

**What NOT to do**:
- Don't explain what LLMs are — the audience knows
- Don't compare to other frameworks by name
- Don't scroll through all 15 reviews — reference "15 product reviews" verbally
- Don't show Python implementation code — keep it on the YAML surface
- Don't rush the context scoping section — that's the differentiator
