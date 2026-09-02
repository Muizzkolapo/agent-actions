# Map / version-merge / fan-in / reduce — shape check

A deterministic workflow that exercises the framework's record-shaping stages with **no
LLM calls**. Every action is `kind: tool`, so it runs offline in about a second and always
produces the same answer — which makes it useful as a regression check when changing
expansion, version merging, fan-in, or FILE-granularity reduction.

## What it covers

| Stage | Actions | Shape |
|---|---|---|
| 1→N expansion | `stage_items` → `split_words` | one record per word of each item |
| Parallel versions + merge | `vote_1`/`vote_2` → `merge_votes` | two voters per record, reduced to one decision |
| Asymmetric fan-in | `merge_votes` + `plain_note` → `fanin_consumer` | a correlation-id branch joined with a plain one |
| Unequal-depth diamond | `split_words` + `plain_note` → `unequal_diamond` | an action fanned in with its own descendant |
| Pre-expansion variants | `vote_direct` → `merge_direct` → `fanin_asymmetric` | the same merge and fan-in before the 1→N split |
| FILE reduce | `reduce_summary` | every fan-in record aggregated into one row |

The two `*_direct` branches are the interesting half: they merge and fan in *before* the
expansion, so only one side of that join carries version correlation ids. That asymmetry
is what the check is really for.

## Run it

```bash
agac inspect -a map_reduce_fanin_check -u tools
agac run -a map_reduce_fanin_check -u tools --fresh
```

No API key is needed — the `.env` placeholder exists only because `agent_actions.yml`
names one.

## Expected output

With the three staged items (two words each), the record counts are fixed:

| Action | Records | |
|---|---|---|
| `stage_items` | 3 | the source items |
| `split_words` | 6 | 3 items × 2 words |
| `merge_votes` | 6 | `n_votes: 2` on each |
| `fanin_consumer` | 6 | `both_branches: true` on every record |
| `unequal_diamond` | 6 | `diamond_ok: true` on every record |
| `merge_direct` | 3 | `n_votes: 2` — merged before expansion |
| `fanin_asymmetric` | 3 | `both_branches: true` |
| `reduce_summary` | 1 | `total_records: 6, fully_merged_records: 6, all_merged: true` |

Any deviation — a missing record, a `false` where the table says `true`, a
`fully_merged_records` below `total_records` — means a join or a merge dropped something.
