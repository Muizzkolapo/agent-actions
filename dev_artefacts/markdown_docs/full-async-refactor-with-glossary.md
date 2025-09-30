---
name: "Full Async Refactor (with Glossary)"
about: "Refactor the agent pipeline for async, with extra onboarding help for new contributors."
labels: [enhancement, async, tech-debt, onboarding]
---

## Summary
Refactor the agent pipeline, runners, and strategies to be fully asynchronous, and expand documentation to help new contributors understand async Python.

## Background: Async Python Glossary (see below)
- **Synchronous (Sync) Code:** Runs one step at a time, waits for each operation to finish.
- **Asynchronous (Async) Code:** Can start a task, then do other things while waiting for it to finish.
- **Coroutine:** A function defined with `async def`, which must be "awaited" to actually run.
- **Await:** The `await` keyword pauses a coroutine until another finishes.
- **Event Loop:** The core system that runs async code (from `asyncio`).
- **Blocking/Non-blocking:** Blocking code stops everything; non-blocking lets other tasks run while waiting.

## Details
- Convert all relevant classes and methods (AgentRunner, strategies, etc.) to use async/await.
- Remove compatibility shims for sync/async.
- Update documentation and onboarding materials to include the glossary above.
- Add examples of how to run and test async code for new contributors.

## Acceptance Criteria
- All async code is properly awaited.
- No use of `asyncio.run` or `run_until_complete` in the core pipeline.
- Documentation and onboarding guide for async concepts is available and clear.
- All tests pass.

---

## Async Python Quick Reference

| Term        | Example Syntax            | What It Means                       |
|-------------|--------------------------|-------------------------------------|
| Coroutine   | `async def foo(): ...`   | An async function                   |
| Await       | `await foo()`            | Wait for a coroutine to finish      |
| Event Loop  | `asyncio.run(foo())`     | Runs coroutines to completion       |
| Blocking    | `time.sleep(1)`          | Stops everything for 1 second       |
| Non-blocking| `await asyncio.sleep(1)` | Lets other tasks run while waiting  |
