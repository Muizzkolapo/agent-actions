# Consensus and Correlated Failures

The terms (item, output, reference, verifier) are defined in `../SKILL.md`.

## 1 How many verifiers

| Verifiers | Vote rule | Verifiers that can be wrong while the item still passes correctly |
|---|---|---|
| 3 | More than half (2 of 3) | 1 |
| 5 | More than half (3 of 5) | 2 |
| 5 | At least 4 of 5 | 1, with fewer false passes |
| 7 | At least 5 of 7 | 2, with fewer false passes |

More verifiers cost one model call each for each item. Choose the smallest set that meets your error budget, measured on items whose reference people checked.

## 2 Correlated failures

Majority voting assumes that verifiers fail independently. Verifiers that share a model, a prompt and a view often fail together:

1. They match on the same surface clue (a word shared by the task and one candidate).
2. They share the same gap in knowledge.
3. They all misread the same unclear source sentence.

Signs: the verifiers agree on almost every item, including items that people later find wrong. Their `reason` texts repeat each other.

## 3 Ways to break the correlation

| Method | How in agent-actions | Cost |
|---|---|---|
| A second model | Set `model_vendor` and `model_name` on one verifier action | One verifier on another provider |
| A different prompt | Give one verifier a prompt that asks for the reasoning first, or a different reading order | Low |
| A refuter | An extra action that gets the blind view and the source and must find a reason the leading choice could be wrong. A tool decides if the refuter's reason holds, or a final judge action reads all reasons | 1 to 2 calls for each item |
| A stricter vote rule | Change the threshold in the comparison tool | More items fail |

## 4 Use the result

1. Guard downstream actions on `compare_with_reference.verified == true`, with `on_false: filter` or `skip`.
2. Keep `detail` (the tally) on the record. Items with a narrow tally are the first to review by hand.
3. Track the verified rate per run. A sudden drop means that the action under test changed, or that the view started to leak or lost information.
