# Lessons Learned

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
