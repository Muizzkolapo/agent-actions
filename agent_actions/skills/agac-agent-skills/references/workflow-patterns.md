# Workflow Design Patterns

These are the building blocks of high-quality workflows. Compose them in phases — each phase narrows, enriches, or validates the record set before the next.

## Diversity Extraction

Run the same extraction action N times with different iteration parameters so each pass surfaces what others missed. Merge into a single canonical set.

```mermaid
flowchart LR
    S[source] --> E1[extract v1]
    S --> E2[extract v2]
    S --> E3[extract v3]
    E1 & E2 & E3 --> C[canonicalize\nversion merge]
    C --> N[next phase]
```

```yaml
- name: extract_raw
  versions: { param: iteration, range: [1, 2, 3], mode: parallel }
  schema: { items: array }

- name: canonicalize
  version_consumption: { source: extract_raw, pattern: merge }
  intent: "Deduplicate and canonicalize across extraction versions"
  context_scope:
    observe: [extract_raw.*]
```

## 1→N Expand

When an LLM returns a list, flatten it into individual records. Each item becomes its own record carrying the full upstream bus.

```mermaid
flowchart LR
    S[source] --> L[extract_items\nreturns list]
    L --> F[flatten\nFile tool]
    F --> R1[record 1]
    F --> R2[record 2]
    F --> RN[record N]
```

```yaml
- name: extract_items      # LLM returns: { items: [...] }

- name: flatten_items
  kind: tool
  impl: flatten_items
  granularity: File         # receives all records; returns one record per item
```

## Semantic Dedup

After expansion, remove near-duplicates before expensive downstream generation. Tag each record with a concept label, then keep the best per concept using a file-mode tool.

```mermaid
flowchart LR
    subgraph in[N records]
        A[record] & B[record] & C[record]
    end
    in --> TC[tag_concept\nLLM]
    TC --> DC[dedup_by_concept\nFile tool]
    subgraph out[M records M≤N]
        X[best per concept]
        Y[best per concept]
    end
    DC --> out
```

```yaml
- name: tag_concept         # LLM: assigns a coarse concept_label
  schema: { concept_label: string }

- name: dedup_by_concept    # File tool: FileUDFResult, keeps best-scoring per concept
  kind: tool
  granularity: File
```

The `dedup_by_concept` tool must return `FileUDFResult` (not `list[dict]`) so its output namespace carries the fields downstream actions need to observe.

## Quality Voting

Run N independent voters. Aggregate by majority. Guard the next phase on the aggregate verdict.

```mermaid
flowchart LR
    R[record] --> V1[vote v1]
    R --> V2[vote v2]
    R --> V3[vote v3]
    V1 & V2 & V3 --> A[aggregate\ntool merge]
    A --> G{decision\n== keep?}
    G -->|pass| N[next phase]
    G -->|filter| X([dropped])
```

```yaml
- name: vote
  versions: { param: voter_id, range: [1, 2, 3], mode: parallel }
  schema: { vote: string, reasoning: string }

- name: aggregate_votes
  kind: tool
  version_consumption: { source: vote, pattern: merge }
  schema: { decision: string, vote_summary: string }

- name: next_phase
  guard: { condition: 'aggregate_votes.decision == "keep"', on_false: "filter" }
  context_scope:
    observe:
      - aggregate_votes.decision   # dependency anchor
```

## Parallel Generate → Consolidate

Generate N independent outputs, then consolidate — pick the best or synthesise across them. Reduces the risk of a single-model pass hallucinating.

```mermaid
flowchart LR
    R[record] --> G1[generate v1]
    R --> G2[generate v2]
    G1 & G2 --> C[consolidate\nversion merge]
    C --> N[next action]
```

```yaml
- name: generate_output
  versions: { param: variant_id, range: [1, 2], mode: parallel }

- name: consolidate_outputs
  version_consumption: { source: generate_output, pattern: merge }
  intent: "Select and ground the best result across independent generations"
  context_scope:
    observe: [generate_output.*]
```

## Distil Before Generating

Extract a tight context window before any generation action observes it. Never pass the full source page to a downstream action — always observe the distilled version.

```mermaid
flowchart LR
    RAW["source.raw_content\n(full page)"]:::danger --> EC[extract_context\ntool]
    REF[upstream_result.source_ref] --> EC
    EC --> CP["context_passage\n(distilled)"]:::good
    CP --> GO[generate_output]
    classDef danger fill:#c44,color:#fff
    classDef good fill:#4a4,color:#fff
```

```yaml
- name: extract_context     # tool: extracts the relevant passage from the source
  context_scope:
    observe:
      - upstream_result.source_ref
      - source.raw_content

- name: generate_output
  context_scope:
    observe:
      - extract_context.context_passage   # distilled passage, not source.raw_content
      - upstream_result.output_text
```

## Verify → Rewrite-if-Failed

Run N verifiers in parallel. Aggregate their verdicts. The rewrite action only fires when failures are confirmed — clean records skip it entirely with `on_false: skip`.

```mermaid
flowchart LR
    O[output] --> V1[verify v1]
    O --> V2[verify v2]
    O --> V3[verify v3]
    V1 & V2 & V3 --> AV[aggregate\nverification]
    AV --> G{has_failures?}
    G -->|true| RW[rewrite\non_false:skip]
    G -->|"false → skip"| NEXT[next action]
    RW --> NEXT
```

```yaml
- name: verify
  versions: { param: verifier_id, range: [1, 2, 3], mode: parallel }
  schema: { passed: boolean, failure_reasons: string }

- name: aggregate_verification
  kind: tool
  version_consumption: { source: verify, pattern: merge }
  schema: { has_failures: boolean, combined_issues: string }

- name: rewrite
  guard: { condition: 'aggregate_verification.has_failures == true', on_false: "skip" }
  context_scope:
    observe:
      - aggregate_verification.combined_issues
      - original_output.*
```

## HITL as Conditional Gate

Route only uncertain records to human review — clear passes skip it. Use `on_false: skip` (not filter) before the HITL action, then a normalize tool merges auto-pass and human-approve into a single boolean.

```mermaid
flowchart LR
    QS[quality_screen] --> G{needs_review?}
    G -->|"true"| HR[human_review\nHITL]
    G -->|"false → skip"| MD
    HR --> MD[merge_decisions\ntool]
    MD --> G2{approved?}
    G2 -->|true| N[next action]
    G2 -->|filter| X([dropped])
```

```yaml
- name: quality_screen
  schema: { passed: boolean, needs_review: boolean, reason: string }

- name: human_review
  kind: hitl
  granularity: file
  guard: { condition: 'quality_screen.needs_review == true', on_false: "skip" }

- name: merge_decisions      # tool: merges auto-pass + human-approve → approved: boolean
  dependencies: [human_review, quality_screen]
  guard: { condition: 'merge_decisions.approved == true', on_false: "filter" }
```
