---
name: "Refactor Agent Pipeline for Full Async Support"
about: "Refactor the agent pipeline, runners, and strategies to be fully async."
labels: [enhancement, async, tech-debt]
---

## Summary
Refactor the agent workflow, runners, and strategies to be fully asynchronous, removing the need for sync/async compatibility shims.

## Details
- Make `AgentRunner`, all strategies, and relevant pipeline components async.
- Propagate `async`/`await` all the way up the stack.
- Remove the compatibility shim from `AgentStrategy._execute_generate_target`.
- Ensure all I/O, API calls, and batch operations use async patterns where possible.
- Update CLI and any orchestration code to run the main event loop as needed.
- Add tests for both sync and async entrypoints.

## Acceptance Criteria
- No use of `asyncio.run` or `run_until_complete` in the core pipeline.
- All async code is properly awaited.
- Sync compatibility layer is removed.
- Documentation updated to reflect new async requirements.
- All tests pass.
