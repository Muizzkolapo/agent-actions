---
name: "Async Python: Glossary & Study Guide"
about: "Break down async/await, coroutines, event loops, and related concepts for new contributors."
labels: [documentation, learning]
---

# Async Python: Glossary & Study Guide

This document explains key terms and concepts related to asynchronous programming in Python, focusing on how they're used in this codebase. It is both a study guide for new contributors and a reference for maintainers.

---

## Key Terms & Concepts

### 1. **Synchronous (Sync) Code**
- Code that runs one step at a time, waiting for each operation to finish before moving to the next.
- Example: Reading a file line by line, where the program waits for the file to finish reading before doing anything else.

### 2. **Asynchronous (Async) Code**
- Code that can start a task and move on to something else before the task is finished.
- Useful for I/O-bound operations (network calls, file I/O) that spend a lot of time waiting.
- Lets your program handle many tasks "at once" (concurrently), even with a single CPU core.

### 3. **Coroutine**
- A special Python function defined with `async def`.
- When called, it returns a **coroutine object** (not the result!).
- Coroutines must be "awaited" to actually run and get their result.
- Example:
  ```python
  async def fetch_data():
      ...
  coro = fetch_data()  # This is a coroutine object
  result = await coro  # This actually runs it
  ```

### 4. **Await**
- The `await` keyword tells Python to pause the current coroutine until another coroutine finishes.
- Only valid inside `async def` functions.

### 5. **Event Loop**
- The core of Python's async machinery (in the `asyncio` module).
- Keeps track of all running coroutines and decides when each one can make progress.
- You start an event loop with `asyncio.run()` or `loop.run_until_complete()`.
- Only one event loop can run in a thread at a time.

### 6. **asyncio**
- Python's built-in library for asynchronous programming.
- Provides event loops, coroutines, tasks, and utilities for async I/O.

### 7. **Blocking vs Non-Blocking**
- **Blocking:** Code that stops everything else until it finishes (e.g., `time.sleep(5)`).
- **Non-blocking:** Code that lets other tasks run while it waits (e.g., `await asyncio.sleep(5)`).

### 8. **Why Use Async?**
- To efficiently handle many I/O-bound tasks (like API calls, file reads/writes, network requests) without using threads or processes.
- Not usually helpful for CPU-bound work (math, heavy computation).

---

## How This Applies to Our Codebase

- Some methods (like `TargetGenerator.generate`) may be **coroutines** (async functions).
- If you call a coroutine like a regular function, you get a coroutine object, not the result, and you get a warning: "coroutine was never awaited".
- To run a coroutine in sync code, you use `asyncio.run()` (if not already in an event loop).
- If already in an event loop (e.g., in a Jupyter notebook), you must use `await` or `loop.run_until_complete()`.
- Our code uses a **compatibility shim** to handle both sync and async cases safely.

---

## Quick Reference Table

| Term        | Example Syntax            | What It Means                       |
|-------------|--------------------------|-------------------------------------|
| Coroutine   | `async def foo(): ...`   | An async function                   |
| Await       | `await foo()`            | Wait for a coroutine to finish      |
| Event Loop  | `asyncio.run(foo())`     | Runs coroutines to completion       |
| Blocking    | `time.sleep(1)`          | Stops everything for 1 second       |
| Non-blocking| `await asyncio.sleep(1)` | Lets other tasks run while waiting  |

---

## Further Reading
- [Python asyncio docs](https://docs.python.org/3/library/asyncio.html)
- [Real Python: Async IO in Python](https://realpython.com/async-io-python/)
- [Brett Cannon: What the heck is the event loop?](https://snarky.ca/what-the-heck-is-the-event-loop/)

