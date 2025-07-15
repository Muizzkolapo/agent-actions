---
name: "Document Async Compatibility Shim in AgentStrategy"
about: "Document the sync/async compatibility shim in _execute_generate_target and its rationale."
labels: [documentation, tech-debt]
---

## Summary
Add developer documentation explaining the compatibility shim in `AgentStrategy._execute_generate_target` for handling both sync and async returns from `TargetGenerator.generate`.

## Details
- Clearly document why `asyncio.iscoroutine` and event loop handling are used.
- Explain that this is a pragmatic solution to support both sync and async code paths without refactoring the entire pipeline.
- Warn maintainers about possible edge cases (e.g., blocking event loop, Jupyter, web servers).
- Add a comment in the code and an entry in the developer docs (e.g., `/docs/dev/async.md` or similar).
- Reference this ticket in the code for future maintainers.

## Acceptance Criteria
- Inline code comments explain the pattern.
- Developer documentation exists and is discoverable.
- Maintainers understand when/why to use this pattern and its limitations.
