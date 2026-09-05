# Species identification — extraction, consensus, grounding

A field-guide pipeline that turns entries into grounded identification notes. It
exists to exercise the framework's stages **combined**, not one at a time: three
version fan-outs with their merges, a 1→N expansion, a FILE-granularity reduce,
four guards — one of them reading a tool's boolean — `drop:` over a merged
parent, seeds, retry and reprompt, all in a single DAG.

Every other example in this tree covers a feature or two. The largest is 14
actions with one fan-out. This is 13 declared actions that expand to 18, with
three fan-outs and four guards, because the interesting failures live in the
combinations rather than in any one directive.

## The shape

| Phase | Actions | What it exercises |
|---|---|---|
| Extract | `summarize_entry` → `extract_field_marks` ×3 → `canonicalize_marks` | parallel versions reduced by a **version merge into an LLM action** — every other merge in this tree feeds a tool |
| | `flatten_marks` | 1→N expansion: one record per canonical mark |
| | `dedupe_across_guides` | **FILE granularity** between two Record-granularity stages — a duplicate is only visible across records |
| Select | `rank_diagnostic_value` ×3 → `aggregate_votes` → `select_approved_marks` | a second fan-out, majority reduce, then a guard on the aggregate's decision |
| Ground | `draft_id_note` ×2 → `consolidate_id_note` | a third fan-out, plus `drop:` applied to fields of a **merged** parent |
| | `locate_supporting_passage` | a tool that answers a boolean two downstream guards read |
| | `describe_confusion_risk`, `auto_review_note` | two actions guarded on that tool's boolean |

## Run it

```bash
agac inspect -a species_id_cards -u tools
agac run -a species_id_cards -u tools --fresh
```

Offline, with no API key: point `model_vendor` at the built-in mock and the whole
pipeline runs in under a second.

```bash
sed -i '' 's/model_vendor: openai/model_vendor: agac-provider/' \
  agent_workflow/species_id_cards/agent_config/species_id_cards.yml
```

## What the run produces

Against the mock provider, with the three staged entries and `record_limit: 2`:

| Stage | Result |
|---|---|
| `summarize_entry` | 2 records |
| `extract_field_marks_1/2/3` | 3 versions per record |
| `canonicalize_marks` | 1 per record — the merge reduced the three |
| `flatten_marks` | one record per canonical mark |
| `dedupe_across_guides` | marks two entries worded identically collapse to one |
| `rank_diagnostic_value_1/2/3` | 3 votes per mark |
| `aggregate_votes` | 1 per mark, `decision` by majority |
| `draft_id_note_1/2` | 2 drafts per surviving mark |
| `locate_supporting_passage` | `passage_found` per note |
| `describe_confusion_risk`, `auto_review_note` | **skipped — every record guard-filtered** |

That last row is the point, not a defect. The mock invents a `supporting_quote`
rather than copying one out of the entry, so `locate_supporting_passage` cannot
find it and answers `passage_found: false`. Both downstream guards then filter
every record, and the run ends `16 completed, 2 skipped`.

A note whose quote is not in the entry it claims to come from is ungrounded, and
the pipeline declines to spend a review on it. Under the mock that is *every*
record — which makes the guard's effect impossible to miss. Against a real model
the same guard passes the notes that quote faithfully and filters the rest.

If you change the grounding rule, this is where you will see it: the run summary
moving off `16 completed, 2 skipped` means a guard stopped firing.

## Two things worth knowing

**`flatten_marks` reports a dag-fit warning, and it is telling the truth.**
`canonicalize_marks` emits `canonical_marks` as an array; `flatten_marks` reaches
inside it and synthesises `mark_text`, `mark_kind` and `species` on new records.
No upstream action guarantees those names, because at the DAG level they do not
exist until the tool creates them. The fields are declared `required: true`
because the tool does set them on every record it emits, which is what the
prompt-contract check reads. The two checks cannot both be satisfied here: the
guarantee is real, but it lives inside a tool rather than in the DAG.

**Array fields declare their item shape.** `extracted_marks.marks` and
`canonical_marks.canonical_marks` both carry an `items:` block. Without it a
downstream tool reaching into the array gets whatever the model returned, and
the failure surfaces as an empty result several actions later rather than as a
schema mismatch at the boundary.
