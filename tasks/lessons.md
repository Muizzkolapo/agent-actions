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
