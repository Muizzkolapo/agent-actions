# Lessons Learned

## 2026-02-07: Flag config errors before writing coercion code

**Failure mode:** User YAML had `file_type: json` (string) where `file_type: [json]` (list) was expected. Instead of telling the user their config was wrong, wrote a Pydantic validator to silently coerce string to list.

**Detection signal:** User called it out — "we dont want clever solution if user did not define well thats what u should have said."

**Prevention rule:** When a runtime error is caused by user config, **tell the user first** with the exact fix. Only add coercion/tolerance code if it's genuinely better DX, and always flag the root cause regardless.

## 2026-02-09: No backwards compatibility shims, no TODO litter

**Failure mode:** Tombstone PR (#943) added legacy fallback checks in `_is_upstream_unprocessed()` to detect old production data missing `_unprocessed` flag. Also planned to add TODO deprecation comments on dead code paths. Both violated AGENTS.md principles.

**Detection signal:** User rejected during review — "no backwards compatibility no to do."

**Prevention rule:** Don't add speculative backward-compat code for data formats that should have been correct. If old data lacks a required field, that's the data's problem. Don't leave TODO comments — either fix it now or don't touch it. Follow "smallest change that works."
