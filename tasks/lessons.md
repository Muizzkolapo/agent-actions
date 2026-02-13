# Lessons Learned

## 2026-02-12: Do not reuse generic `status` aliases in HITL payload paths

**Failure mode:** Keeping backward-compat `status` fallbacks in HITL server/pipeline created a collision risk with business data fields named `status`, making approval flows appear to mutate domain status.

**Detection signal:** User reported that status changed on approval.

**Prevention rule:** HITL paths must use `hitl_status` as the only decision key; when merging HITL decisions into records, whitelist HITL metadata keys instead of passing through arbitrary response keys.

## 2026-02-12: Use domain-specific status keys in cross-stage payloads

**Failure mode:** HITL decision payload used generic `status`, which can collide with existing record fields and make guard expressions ambiguous.

**Detection signal:** User explicitly requested `hitl_status` instead of `status`.

**Prevention rule:** For stage-specific control fields, use namespaced keys (`hitl_status`, `batch_status`, etc.) and normalize legacy aliases only at boundaries.

## 2026-02-12: Separate record actions from final workflow submission in HITL

**Failure mode:** Mapped Approve/Reject buttons directly to final submit, which blocked per-record review flow and made users manually navigate without decision state.

**Detection signal:** User asked for automatic next-object progression immediately after approving current object.

**Prevention rule:** For multi-record HITL UX, treat record-level decisions and final workflow release as two distinct actions: mark record (auto-advance) then submit all.

## 2026-02-12: FILE-level decisions still need per-record output propagation

**Failure mode:** Implemented FILE-mode HITL to emit a single decision output record, which unintentionally dropped the original dataset cardinality for downstream stages.

**Detection signal:** User noticed only one record was written as approved.

**Prevention rule:** For FILE-level gate/review actions, separate "decision cardinality" from "output cardinality": one decision can apply to many records, but downstream record streams must be preserved unless explicitly aggregated.

## 2026-02-12: File-level HITL needs navigable review UX, not a raw blob

**Failure mode:** Treated FILE-mode HITL as "show one full JSON payload" in UI, which made large reviews unusable even though backend file-level semantics were correct.

**Detection signal:** User clarified they need to move record-by-record ("go to next record each time") while keeping HITL at file level.

**Prevention rule:** For any FILE-level human review step, verify UX requirements separately from backend granularity: reviewers must be able to navigate records even when final decision is single-shot.

## 2026-02-07: Flag config errors before writing coercion code

**Failure mode:** User YAML had `file_type: json` (string) where `file_type: [json]` (list) was expected. Instead of telling the user their config was wrong, wrote a Pydantic validator to silently coerce string to list.

**Detection signal:** User called it out — "we dont want clever solution if user did not define well thats what u should have said."

**Prevention rule:** When a runtime error is caused by user config, **tell the user first** with the exact fix. Only add coercion/tolerance code if it's genuinely better DX, and always flag the root cause regardless.

## 2026-02-09: Removing dead-code guards can break live side effects

**Failure mode:** `create_passthrough_output` had `if self.storage_backend is None: output_dir.mkdir(...)`. After making storage_backend mandatory (ConfigurationError in constructor), the guard became always-false dead code. Removed it as "cosmetically correct" — but the `mkdir` was still needed for the `shutil.copy2` calls that follow. Result: passthrough file copies silently failed (FileNotFoundError swallowed by try/except), downstream agents got empty input.

**Detection signal:** External audit traced the full call path and noticed the directory was never created.

**Prevention rule:** When removing a conditional guard, trace all code that *depended on* the guarded side effect, not just the guard condition. Ask: "what was the side effect, and does anything downstream still need it?"

## 2026-02-09: No backwards compatibility shims, no TODO litter

**Failure mode:** Tombstone PR (#943) added legacy fallback checks in `_is_upstream_unprocessed()` to detect old production data missing `_unprocessed` flag. Also planned to add TODO deprecation comments on dead code paths. Both violated AGENTS.md principles.

**Detection signal:** User rejected during review — "no backwards compatibility no to do."

**Prevention rule:** Don't add speculative backward-compat code for data formats that should have been correct. If old data lacks a required field, that's the data's problem. Don't leave TODO comments — either fix it now or don't touch it. Follow "smallest change that works."
