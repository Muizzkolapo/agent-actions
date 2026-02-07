# Lessons Learned

## 2026-02-07: Flag config errors before writing coercion code

**Failure mode:** User YAML had `file_type: json` (string) where `file_type: [json]` (list) was expected. Instead of telling the user their config was wrong, wrote a Pydantic validator to silently coerce string to list.

**Detection signal:** User called it out — "we dont want clever solution if user did not define well thats what u should have said."

**Prevention rule:** When a runtime error is caused by user config, **tell the user first** with the exact fix. Only add coercion/tolerance code if it's genuinely better DX, and always flag the root cause regardless.
