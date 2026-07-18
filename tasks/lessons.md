# Lessons — clone_3 harness runs

## 581 — a "dead code" claim from a prior review must be re-verified before you touch it

**Failure mode:** Spec 581 was drafted from 573's blast-radius follow-up, which claimed
`sqlite_backend.write_checkpoint_output` was dead (zero callers/tests/interface refs). The
spec Task 1 offered "if genuinely dead → delete the method." Grepping for that exact name
returned nothing — which under a shallow reading would prove "still dead, delete it." But
the method with the flagged `r.get("source_guid", "")` fallback at line 1056, the
`INSERT OR REPLACE` at line 1065, and the `UNIQUE(action_name, relative_path, source_guid)`
schema is actually `save_checkpoint_records`, and it is:
- on the `StorageBackend` interface (`backend.py:534` — required override), and
- called in production by `online_llm.py:310` from `_checkpoint_record`, and
- exercised by tests, and
- documented as a core protocol step in `storage/ARCHITECTURE.md`.

Deleting it would have broken online resume silently at first, loudly on the next resume.

**Detection signal:** the spec names a specific symbol/file/line as "dead," but the
prior review's summary predates the current commit. Before treating anything as dead:
grep for the exact name AND the surrounding code fingerprints (SQL constants, error
messages, `INSERT OR REPLACE` table refs, arg-list shape). If the name doesn't match but
the fingerprint does, the code was renamed, not deleted.

**Prevention rule:** for a follow-up spec that inherits a "dead code" claim from a prior
review, do the dead-check yourself against HEAD: (a) grep the name across the repo AND
docs/manifests; (b) grep the code fingerprint the spec quoted (SQL literal, method body,
signature); (c) check the base-class interface for a same-shape signature; (d) check the
producer chain (`ARCHITECTURE.md`) for whether the concept is still live. If (b) matches
under a different name, the correct treatment is HARDEN, not DELETE — and the PR must
name the deviation (spec said X, actual is Y with the same shape).

## 581 — a HIGH-risk verdict from an affirmative reviewer body is still information

**Failure mode:** Lens B's body was entirely YES ("callers safe, no siblings, tests pass,
compatible with the contract, ARCHITECTURE gap is soft — not a correctness bug") but the
final line read `VERDICT: NO`. The temptation is to treat the header as authoritative
and either dismiss the reviewer or bounce the diff.

**Prevention rule:** read the body, not the header. A blind reviewer's soft findings
("would be nice") are still worth addressing when they cost nothing — extending
`ARCHITECTURE.md` Note 11 to name `save_checkpoint_records` cost one sentence and closed
the doc-parity gap Lens B named. Record `YES_WITH_ISSUES` after addressing, not `NO`, when
the body is affirmative. Do NOT rerun another reviewer round to "confirm" — that's just
laundering a soft finding into a stronger vote and burns tokens for no signal.

## 582 — a static "was this key definitely set" scan must skip nested function bodies

**Failure mode:** `_last_return` used `ast.walk(func)` to pick the tail return by lineno. `ast.walk` descends into every child node — including nested `FunctionDef` / `AsyncFunctionDef` / `Lambda` bodies inside the outer function. A helper defined below the outer's tail return (dead code, but valid syntax) provides a return at a higher lineno and gets picked as the outer's tail. If that inner return happens to be a dict literal containing a field the outer only conditionally emits, the field is silently exonerated — the whole detector misses the exact class of bug it exists to catch. A blind correctness reviewer flagged it before merge; unit tests missed it because they were all single-function fixtures.

**Detection signal:** the reviewer traced `_last_return` line by line and asked "does `ast.walk` distinguish between the outer function's returns and a nested helper's returns?" — a direct question about the traversal contract, not something a happy-path unit test surfaces.

**Prevention rule:** when a static-AST check reasons about a function's OWN control flow (returns, top-level statements, "what runs unconditionally"), never use `ast.walk` on the function node — write a bounded walker that starts from `func.body` and stops descending at nested `FunctionDef` / `AsyncFunctionDef` / `Lambda` nodes. Add a regression fixture with a nested helper defined after the outer's tail return; it costs one paragraph and closes the pathological hole a reviewer will otherwise ask about.

## 593 — verify the persisted record shape before gating on a namespace key

**Failure mode:** Spec 593's RED sketches described the checkpoint / online-result records as
top-level `{"source_guid": ..., "<action>": value}`. The real shape is content-nested
`{"source_guid": ..., "content": {"<action>": value}}` — produced by
`transform_with_passthrough` → `RecordEnvelope.build`, and confirmed by `disposition_gate`
reading `read_checkpoint_records` and `read_target` output interchangeably (same
`r["source_guid"]` key, same downstream carry-forward). A gate written against the spec's
stated shape would read `record["<action>"]` — always `None` — making the whole gate a
**silent no-op** that a naive top-level-shaped test would still pass.

**Detection signal:** the already-merged 556 gate (`_gate_schema_echo_deltas`) read
`record["content"][action_name]`; the spec proposed *reusing* it but described a different
record shape. Two seams claiming to share one predicate while disagreeing on the record
shape is the tell — one of them is wrong about the shape.

**Prevention rule:** before gating/reading a namespace on a persistence path, trace the
producer (`transform_with_passthrough`) and an existing consumer that treats the two seams
interchangeably, to pin the exact key. A spec's example record shape is a claim to verify
against the producer, not a fact — especially when an existing sibling gate on the same
value already reads a different key. Build the RED fixture from the real compiled shape
(`compile_unified_schema(..., "ollama_cloud")`) so a wrong key can't accidentally pass.
