# Display Ids

The terms (item, output, reference, candidate, verifier, blind view) are defined in `../SKILL.md`.

## 1 Why real ids leak

Real ids are often made in the order that the output lists things. Then the id itself tells which candidate matches the reference:

| Task | Real ids | The leak |
|---|---|---|
| Choose the category of a document | `cat_1` is always the category the classifier chose | Choose `cat_1` |
| Put the steps of a procedure in order | `step_1 .. step_N` in the reference order | Sort by id |
| Pair contract clauses with their risk labels | `clause_3` pairs with `risk_3` | Pair equal suffixes |
| Keep the line items that belong to an invoice | `item_*` are kept, `extra_*` are added decoys | Keep the `item_` prefix |

Every static check passes: the verifiers' `observe` list is correct. The reference leaks through the blind view itself.

## 2 The fix

In `build_blind_view`:

1. Shuffle the candidates with a seed made from the item's content, so a rerun gives the same view.
2. Give display ids in the shuffled order, with one neutral prefix (`c1`, `c2`, ...). For two columns, use one prefix for each column (`p1..pN`, `q1..qM`) and shuffle each column separately.
3. Show the verifier only `{display_id, text}` for each candidate.
4. Return the map `display_to_real` as a separate field. Only the comparison tool observes it.
5. For an ordered task, shuffle again until neither the list order nor the id order equals the reference order. A random shuffle of 3 items is sometimes still in order.

```python
import hashlib
import random
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def build_blind_view(data: dict[str, Any]) -> dict[str, Any]:
    out = data.get("classify_document") or {}
    candidates = [c for c in out.get("candidates") or [] if isinstance(c, dict)]
    seed = int(hashlib.sha256(("view\x00" + str(out.get("document_id"))).encode()).hexdigest(), 16)
    order = list(range(len(candidates)))
    random.Random(seed).shuffle(order)
    lines, display_to_real = [], {}
    for n, i in enumerate(order, start=1):
        display_id = f"c{n}"
        display_to_real[display_id] = candidates[i].get("id")
        lines.append(f"{display_id}: {candidates[i].get('text', '')}")
    return {"view_text": "\n".join(lines), "display_to_real": display_to_real}
```

## 3 The verifier prompt

1. Say that the ids are arbitrary labels and carry no order.
2. Show an output example whose id is not the first (`{"chosen_id": "c3", "reason": "..."}`).
3. Ask for the reason before the choice in the output, so the verifier reads the source first.

## 4 Other leaks to remove

| Leak | Fix |
|---|---|
| The matching candidate is always the longest or the most detailed | Make the candidates similar in length, or tell the action under test to |
| One candidate repeats the words of the task | Rewrite the task in neutral words |
| A mark such as "recommended" or "default" | Remove marks from the view |
| The same shuffle in the view that people see later | Use a different seed for each view |

## 5 Check the view

Before a full run, read 3 rendered prompts: `agac traces -w <workflow> -A verify_1`. Ask: could a reader with no access to the source choose the reference from this text alone? If yes, the view still leaks.
