# Prompt Engineering

**One unit of outcome per action.** Each action produces exactly one thing — a concept tag, an extracted passage, a ranked candidate list. Actions that attempt two things produce worse output on both. If a prompt has two `##` output sections, split it into two actions.

**Anchor on distilled inputs.** The prompt should receive the smallest context window that contains what it needs. A question-writing action needs the relevant quote and the Q&A pair — not the full source page. Enforce this at the config level: extract the context first, then observe the extracted field.

**Seed data for invariants.** Exam syllabi, authoring rules, and few-shot examples belong in seed files, not embedded in prompt text. Reference as `{{ seed.key.subkey }}`. Seed content is stable across records — putting it in the prompt text repeats it every LLM call for nothing.

**Strict output contracts.** An explicit contract block in the prompt, combined with `additionalProperties: false` in the schema, is the most reliable way to keep output parseable. Put it at the end of every generation prompt:

```
STRICT OUTPUT CONTRACT
- Output valid JSON only — no prose, no markdown fences
- Do not add fields not listed above
- Do not escape special characters in string values
```

**Version diversity.** When running N parallel versions, vary the instruction angle slightly across versions — different emphasis, different framing — to reduce correlation. Correlated voters add noise without adding signal.

**Guard prompts as decision anchors.** Guard-feeding actions should return a simple, unambiguous boolean or enum — not a prose judgement. Downstream guards evaluate exactly that field. Keep the reasoning in a separate `reasoning` field so it's on the bus but not in the gate condition.
