# FILE-Level Lineage Fix: Current vs Proposed RFC

This document compares the current fix (PR #634) with the proposed RFC (Issue #633) for handling lineage in FILE-level UDFs.

## Overview

| Aspect | Current Fix (PR #634) | Proposed RFC (#633) |
|--------|----------------------|---------------------|
| Contract | Implicit | Explicit |
| UDF Return Type | `List[Dict]` | `FileUDFResult` |
| Lineage Source | Preserved in output | Explicit mapping |
| Many-to-Many | Not supported | Supported |
| Breaking Change | No | No (optional) |
| Status | Done | Future work |

---

## Current Fix (PR #634) - Implicit Contract

```mermaid
flowchart TB
    subgraph INPUT["INPUT RECORDS"]
        A["Record A<br/>lineage: [node_2_a]"]
        B["Record B<br/>lineage: [node_2_b]"]
        C["Record C<br/>lineage: [node_2_c]"]
    end

    subgraph UDF["FILE-LEVEL UDF (run_dedup)"]
        U1["Receives all records as list"]
        U2{"UDF developer<br/>deep copies?"}
        U3["json.loads(json.dumps(item))<br/>Preserves lineage"]
        U4["item.copy() or new dict<br/>Loses lineage"]
        U5["Returns List[Dict]"]
    end

    subgraph FRAMEWORK["FRAMEWORK POST-PROCESSING"]
        F1["For each output item:"]
        F2{"'lineage' in item<br/>and is list?"}
        F3["source_item = item<br/>(use preserved lineage)"]
        F4["source_item = data[0]<br/>(fallback to first input)"]
        F5["LineageBuilder.add_lineage_tracking()"]
    end

    subgraph OUTPUT["OUTPUT RECORDS"]
        O1["Result 1<br/>lineage: [..., node_2_a, node_3_0]"]
        O2["Result 2<br/>lineage: [..., node_2_c, node_3_1]"]
    end

    INPUT --> U1
    U1 --> U2
    U2 -->|"Yes (knows contract)"| U3
    U2 -->|"No (unaware)"| U4
    U3 --> U5
    U4 --> U5
    U5 --> F1
    F1 --> F2
    F2 -->|"Yes"| F3
    F2 -->|"No"| F4
    F3 --> F5
    F4 --> F5
    F5 --> OUTPUT

    style U2 fill:#ffcc00,stroke:#333
    style F2 fill:#87ceeb,stroke:#333
    style U3 fill:#90ee90,stroke:#333
    style U4 fill:#ffcccb,stroke:#333
```

### How It Works

1. **UDF receives all records** as a list
2. **UDF processes records** (filter, transform, etc.)
3. **If UDF developer deep-copies records**, lineage is preserved
4. **Framework checks** if output has `lineage` field
5. **If yes**, use preserved lineage; **if no**, fallback to first input

### Code Change

```python
# target_content_processor.py lines 349-354
if 'lineage' in item and isinstance(item['lineage'], list):
    source_item = item  # UDF preserved lineage - use it
else:
    source_item = fallback_source  # Legacy fallback
```

### Limitations

- UDF must "know" to preserve lineage via deep copy
- No explicit mapping - framework guesses from preserved lineage
- Cannot handle many-to-many (merging multiple inputs)

---

## Proposed RFC (#633) - Explicit Contract

```mermaid
flowchart TB
    subgraph INPUT["INPUT RECORDS (indexed)"]
        A["idx=0: Record A<br/>lineage: [node_2_a]"]
        B["idx=1: Record B<br/>lineage: [node_2_b]"]
        C["idx=2: Record C<br/>lineage: [node_2_c]"]
    end

    subgraph UDF["FILE-LEVEL UDF (run_dedup)"]
        U1["Receives all records as list"]
        U2["Process records<br/>Track which input -> which output"]
        U3["Build source_mapping:<br/>{0: 0, 1: 2}"]
        U4["Return FileUDFResult(<br/>  outputs=[...],<br/>  source_mapping={0:0, 1:2}<br/>)"]
    end

    subgraph FRAMEWORK["FRAMEWORK POST-PROCESSING"]
        F1["Detect FileUDFResult type"]
        F2["For each output_idx:"]
        F3{"source_mapping<br/>has output_idx?"}
        F4["input_idx = mapping[output_idx]<br/>source = data[input_idx]"]
        F5["Fallback to data[0]"]
        F6{"mapping value<br/>is list?"}
        F7["Single parent:<br/>use data[input_idx].lineage"]
        F8["Multiple parents:<br/>merge lineages"]
        F9["LineageBuilder.add_lineage_tracking()"]
    end

    subgraph OUTPUT["OUTPUT RECORDS"]
        O1["Result 1<br/>lineage: [..., node_2_a, node_3_0]"]
        O2["Result 2<br/>lineage: [..., node_2_c, node_3_1]"]
    end

    INPUT --> U1
    U1 --> U2
    U2 --> U3
    U3 --> U4
    U4 --> F1
    F1 --> F2
    F2 --> F3
    F3 -->|"Yes"| F4
    F3 -->|"No"| F5
    F4 --> F6
    F5 --> F9
    F6 -->|"int"| F7
    F6 -->|"list"| F8
    F7 --> F9
    F8 --> F9
    F9 --> OUTPUT

    style U3 fill:#90ee90,stroke:#333
    style U4 fill:#90ee90,stroke:#333
    style F6 fill:#87ceeb,stroke:#333
    style F8 fill:#dda0dd,stroke:#333
```

### How It Works

1. **UDF receives all records** as a list with indices
2. **UDF processes records** and tracks input→output mapping
3. **UDF returns `FileUDFResult`** with explicit `source_mapping`
4. **Framework reads mapping** to determine lineage
5. **Supports single or multiple parents** per output

### Proposed Code

```python
@dataclass
class FileUDFResult:
    outputs: List[Dict]
    source_mapping: Optional[Dict[int, Union[int, List[int]]]] = None
    # {output_idx: input_idx} or {output_idx: [input_idx1, input_idx2]}

@udf_tool(granularity=Granularity.FILE)
def run_dedup(items: List[Dict]) -> FileUDFResult:
    seen = {}
    mapping = {}

    for input_idx, item in enumerate(items):
        key = item['content']['fact']
        if key not in seen:
            output_idx = len(seen)
            seen[key] = item
            mapping[output_idx] = input_idx

    return FileUDFResult(
        outputs=list(seen.values()),
        source_mapping=mapping
    )
```

### Benefits

- Explicit contract - UDF declares exactly where outputs came from
- No guessing - framework uses mapping directly
- Supports many-to-many (merge scenarios)

---

## Side-by-Side Comparison

```mermaid
flowchart LR
    subgraph CURRENT["CURRENT FIX (PR #634)"]
        direction TB
        C1["UDF returns List[Dict]"]
        C2["Framework checks:<br/>has lineage field?"]
        C3["Yes -> use it"]
        C4["No -> fallback"]
        C1 --> C2
        C2 --> C3
        C2 --> C4
    end

    subgraph RFC["PROPOSED RFC (#633)"]
        direction TB
        R1["UDF returns FileUDFResult"]
        R2["Framework reads:<br/>source_mapping"]
        R3["output[i] -> input[j]"]
        R4["Supports merges:<br/>output[i] -> input[j,k,l]"]
        R1 --> R2
        R2 --> R3
        R2 --> R4
    end

    CURRENT -.->|"Evolution"| RFC

    style C1 fill:#ffffcc,stroke:#333
    style R1 fill:#ccffcc,stroke:#333
    style C4 fill:#ffcccb,stroke:#333
    style R4 fill:#90ee90,stroke:#333
```

---

## Many-to-Many Scenario (RFC Only)

This scenario is **not supported** by the current fix but **is supported** by the proposed RFC.

```mermaid
flowchart TB
    subgraph INPUT["3 INPUT RECORDS"]
        A["Record A (idx=0)"]
        B["Record B (idx=1)"]
        C["Record C (idx=2)"]
    end

    subgraph UDF["MERGE UDF"]
        M["group_by_similarity()<br/>Combines similar records"]
        MAP["source_mapping = {<br/>  0: [0, 1, 2]<br/>}"]
    end

    subgraph OUTPUT["1 OUTPUT RECORD"]
        O["Merged Record<br/>lineage_sources: [<br/>  [node_2_a],<br/>  [node_2_b],<br/>  [node_2_c]<br/>]"]
    end

    A --> M
    B --> M
    C --> M
    M --> MAP
    MAP --> O

    style MAP fill:#dda0dd,stroke:#333
    style O fill:#90ee90,stroke:#333
```

### Example: Merge UDF with RFC

```python
@udf_tool(granularity=Granularity.FILE)
def group_by_similarity(items: List[Dict]) -> FileUDFResult:
    groups = {}  # group_id -> (merged_item, input_indices)

    for input_idx, item in enumerate(items):
        group_id = item['content']['similarity_group_id']
        if group_id not in groups:
            groups[group_id] = (item.copy(), [input_idx])
        else:
            groups[group_id][1].append(input_idx)

    outputs = []
    mapping = {}
    for output_idx, (merged, input_indices) in enumerate(groups.values()):
        outputs.append(merged)
        mapping[output_idx] = input_indices  # Multiple parents!

    return FileUDFResult(outputs=outputs, source_mapping=mapping)
```

---

## Decision Flow: Which Approach Handles What?

```mermaid
flowchart TB
    START["FILE-level UDF<br/>processes records"]

    Q1{"Scenario?"}

    FILTER["Filter/Dedup<br/>(N inputs -> M outputs,<br/>M <= N)"]
    TRANSFORM["Transform<br/>(1 input -> 1 output)"]
    MERGE["Merge/Aggregate<br/>(N inputs -> 1 output)"]

    CURRENT1["Current Fix: Supported<br/>UDF preserves lineage"]
    CURRENT2["Current Fix: Supported<br/>UDF preserves lineage"]
    CURRENT3["Current Fix: NOT SUPPORTED<br/>Cannot express<br/>multiple parents"]

    RFC1["RFC: Supported<br/>mapping: {0:0, 1:2}"]
    RFC2["RFC: Supported<br/>mapping: {0:0, 1:1}"]
    RFC3["RFC: Supported<br/>mapping: {0:[0,1,2]}"]

    START --> Q1
    Q1 --> FILTER
    Q1 --> TRANSFORM
    Q1 --> MERGE

    FILTER --> CURRENT1
    FILTER --> RFC1

    TRANSFORM --> CURRENT2
    TRANSFORM --> RFC2

    MERGE --> CURRENT3
    MERGE --> RFC3

    style CURRENT3 fill:#ffcccb,stroke:#333
    style RFC3 fill:#90ee90,stroke:#333
```

---

## Summary

| Scenario | Current Fix | Proposed RFC |
|----------|-------------|--------------|
| Filter (N→M, M≤N) | ✅ Works (if lineage preserved) | ✅ Works (explicit mapping) |
| Transform (1→1) | ✅ Works (if lineage preserved) | ✅ Works (explicit mapping) |
| Dedup (N→M unique) | ✅ Works (if lineage preserved) | ✅ Works (explicit mapping) |
| Merge (N→1) | ❌ Cannot express multiple parents | ✅ Works ({0: [0,1,2]}) |
| Aggregate (N→1) | ❌ Cannot express multiple parents | ✅ Works ({0: [0,1,...,N-1]}) |

---

## References

- **Current Fix**: [PR #634](https://github.com/Muizzkolapo/agent-actions/pull/634)
- **Proposed RFC**: [Issue #633](https://github.com/Muizzkolapo/agent-actions/issues/633)
- **File Changed**: `agent_actions/prompt_generation/target_content_processor.py`
