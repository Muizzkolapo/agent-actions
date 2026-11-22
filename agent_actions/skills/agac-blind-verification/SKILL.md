---
name: agac-blind-verification
description: Check model outputs with independent verifiers that never see the reference, in agent-actions workflows. Triggers on blind verification, independent verifiers, majority vote, consensus, verifier agreement, display ids, hidden reference, label checking, extraction QA, grading checks, fact checking, correlated verifier errors, or "the verifiers agree but the output is still wrong".
---

# Agent Actions Blind Verification

Check model outputs with independent verifiers that never see the reference, in agent-actions workflows.

A verifier that can see the reference agrees with it. A verifier that sees ids or an order that reveal the reference finds it without reading the source. Blind verification removes both leaks. Several verifiers produce their own output from the source alone, and a tool compares their outputs with the reference that only the tool can see.

Use it for extraction QA (does the extracted total match the invoice?), data labelling (does the label fit the document?), grading checks (is the chosen category the one the policy names?) and fact checks (does the source support the claim?).

## Terms

One term has one meaning in this skill.

| Term | Meaning |
|---|---|
| item | The unit that is checked: one record, or one part of a record |
| source | The material the item comes from: a document, a ticket, a page |
| output | What the action under test produced for the item |
| reference | The value the check compares against: the output under test, or a value from people. Only the comparison tool sees it |
| candidate | One option that a verifier can choose, when the item offers options |
| verifier | A model call that produces its own output for the item, from the source and the blind view only |
| blind view | What a verifier sees: the task and the candidates, with no reference and no id that reveals it |
| comparison tool | The tool action that maps the verifiers' outputs back and compares them with the reference |

## Rules

1. **Verifiers never see the reference.** Their `observe` lists only the blind view and the source. No field of the action under test that holds the reference, and no field that is derived from it.
2. **Ids in the blind view must not reveal the reference.** Ids made in the order of the output (`c1` is always the first-listed match, `item_1` pairs with `label_1`) let a verifier match by id. Give display ids after a shuffle, and keep the map from display id to real id out of the verifiers' view.
3. **The comparison is code.** A tool compares the verifiers' outputs with the reference. A model never decides if the outputs match.
4. **Decide the vote rule before you look at results.** A strict majority (more than half) is the default. A stricter rule (for example, all verifiers or 4 of 5) trades kept items for fewer false passes.
5. **Treat agreement as evidence, not proof.** Verifiers of the same model can fail in the same way. Use a second model, a refuter, or both, where a false pass is costly (see [references/consensus.md](references/consensus.md)).

## The pattern

```yaml
- name: build_blind_view
  dependencies: [classify_document]
  kind: tool
  impl: build_blind_view
  intent: Shuffle the candidates, give display ids, keep the reference out of the view
  schema:
    view_text: string
    display_to_real: object
  context_scope:
    observe:
      - classify_document.*

- name: verify_1
  dependencies: [build_blind_view]
  intent: Choose the category from the document alone
  schema:
    chosen_id: string
    reason: string
  prompt: $my_workflow.Verify_Category
  context_scope:
    observe:
      - build_blind_view.view_text
      - source.document_text

- name: verify_2
  dependencies: [build_blind_view]
  intent: Choose the category from the document alone
  schema:
    chosen_id: string
    reason: string
  prompt: $my_workflow.Verify_Category
  context_scope:
    observe:
      - build_blind_view.view_text
      - source.document_text

- name: verify_3
  dependencies: [build_blind_view]
  intent: Choose the category from the document alone
  schema:
    chosen_id: string
    reason: string
  prompt: $my_workflow.Verify_Category
  context_scope:
    observe:
      - build_blind_view.view_text
      - source.document_text

- name: compare_with_reference
  dependencies: [verify_1, verify_2, verify_3, build_blind_view, classify_document]
  kind: tool
  impl: compare_with_reference
  intent: Map the chosen display ids back and compare them with the reference
  schema:
    verified: boolean
    matches: integer
    detail: string
  context_scope:
    observe:
      - verify_1.chosen_id
      - verify_2.chosen_id
      - verify_3.chosen_id
      - build_blind_view.display_to_real
      - classify_document.category_id
```

The 3 verifiers are sibling actions with the same prompt. Only `compare_with_reference` observes `display_to_real` and the reference (`classify_document.category_id`).

```python
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def compare_with_reference(data: dict[str, Any]) -> dict[str, Any]:
    view = data.get("build_blind_view") or {}
    to_real = {str(k).strip().lower(): v for k, v in (view.get("display_to_real") or {}).items()}
    reference = (data.get("classify_document") or {}).get("category_id")
    chosen = [(data.get(name) or {}).get("chosen_id") for name in ("verify_1", "verify_2", "verify_3")]
    real = [to_real.get(str(c or "").strip().lower(), c) for c in chosen]
    matches = sum(1 for r in real if r == reference)
    return {
        "verified": matches * 2 > len(real),
        "matches": matches,
        "detail": f"{matches}/{len(real)} verifiers chose the reference",
    }
```

An unknown display id passes through unchanged, so it never matches the reference by accident. A verifier that returned nothing counts as a non-match.

## Building the blind view

Read [references/display-ids.md](references/display-ids.md) before you write `build_blind_view`. In short:

1. Shuffle the candidates with a seed made from the item's content, so a rerun gives the same view.
2. Give display ids in the shuffled order (`c1`, `c2`, ...), with no prefix or suffix that tells which group a candidate came from.
3. Put the same shuffle in no other view. A view that people see later uses its own shuffle.
4. In the verifier prompt, say that the ids are arbitrary labels. Show an example whose ids are not in order (`chosen_id: "c3"`).

## When a judge rule is enough

An `llm_judge` expectation (see the `agac-expectations` skill) sees the field it checks and the `context:` fields. Use it when the judge needs no hidden reference: "the summary states only facts in the ticket". Use blind verification when the check compares with a reference that the verifier must not see, or when the view needs a shuffle or display ids first.

## Gotchas

1. **A leak through the view passes every static check.** Preflight sees a correct `observe` list, but the view text itself can hold the reference (an id order, a "recommended" mark, a longer candidate). Read 3 rendered verifier prompts with `agac traces -w <workflow> -A verify_1` before a full run.
2. **A verifier that observes `classify_document.*` sees the reference.** A wildcard on the action under test gives the verifier every field of it. Name the fields of the blind view, not a wildcard of that action.
3. **Same model, same blind spot.** If all verifiers miss the same kind of error, a majority does not help. Add a verifier on a different model, or a refuter.

See [Context scope](https://docs.runagac.com/docs/reference/context/context-scope), [Guards](https://docs.runagac.com/docs/reference/execution/guards) and [Custom tools](https://docs.runagac.com/docs/guides/custom-tools).
