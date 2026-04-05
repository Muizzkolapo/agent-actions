# AI Coding Agent Guidelines

These rules define how an AI coding agent should plan, execute, verify, communicate, and recover when working in a real codebase. Optimize for correctness, minimalism, and developer experience.

---

## Project Structure

This project uses the **Agent Manifest Protocol (AMP)** — a per-module navigation and impact map. Every module has a `_MANIFEST.md`.

**[> Open Codebase Map (agent_actions/_MANIFEST.md)](agent_actions/_MANIFEST.md)**

### Navigation Strategy

1. **Start Here:** Use this file for high-level context.
2. **Find the module:** Follow the root `_MANIFEST.md` link above to find the module you need.
3. **Read the manifest:** Each module's `_MANIFEST.md` tells you what it does, what user project files it touches, and what depends on it.
4. **Assess impact:** Before changing code, read the `## Project Surface` table to see what user-facing files your change affects. Read `## Dependencies` to see what other modules will be impacted.
5. **Read code:** Only read source files after the manifest has pointed you to the right location.

### Manifest Structure

Every `_MANIFEST.md` has these sections in this order:

| Section | Purpose | Parseable |
|---------|---------|-----------|
| `# {Module Name}` | Module name and one-line description | Yes |
| `## Sub-Modules` | Links to nested package manifests (optional) | Yes |
| `## Modules` | Table of source files, types, exports, signals | Yes |
| `## Project Surface` | What user project files this module reads/writes/validates | Yes |
| `## Dependencies` | What depends on this module and what it depends on | Yes |
| `## Notes` | Design decisions, gotchas, diagrams (optional) | No |

The parseable sections use standardized table headers so tooling can extract JSON from markdown. See `bin/manifest-to-json.py`.

### Project Surface — Impact Assessment

The `## Project Surface` table maps framework symbols to user project files:

```
| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
```

These are the **stable paths** that exist in every user's project:

| Path | What it is |
|------|-----------|
| `agent_actions.yml` | Project config |
| `agent_config/{workflow}.yml` | Workflow definition |
| `prompt_store/{workflow}.md` | Prompt templates |
| `schema/{workflow}/{action}.yml` | Output schemas |
| `tools/{workflow}/*.py` | UDF tool scripts |
| `seed_data/*.json` | Reference data |
| `agent_io/staging/` | Input data |
| `agent_io/target/{action}/` | Output data per action |
| `.env` | Environment variables |

Use this to answer: "I'm changing this code — what user files does it affect?" Or in reverse: "Something broke in my config — what framework code touches it?"

### Manifest Maintenance

When making code changes:
- **Add/remove a module**: Update the `## Modules` table.
- **Change what a symbol reads/writes**: Update the `## Project Surface` table.
- **Add/remove a module dependency**: Update the `## Dependencies` table.
- **New sub-package**: Create a `_MANIFEST.md` in it and link from the parent's `## Sub-Modules`.

### Development

- **Install:** `uv sync`
- **Activate:** `source .venv/bin/activate`
- **Test:** `pytest`
- **Lint:** `ruff check .`
- **Format:** `ruff format .`

---

## Operating Principles (Non-Negotiable)

- **Correctness over cleverness**: Prefer boring, readable solutions that are easy to maintain.
- **Smallest change that works**: Minimize blast radius; don't refactor adjacent code unless it meaningfully reduces risk or complexity.
- **Leverage existing patterns**: Follow established project conventions before introducing new abstractions or dependencies.
- **Prove it works**: "Seems right" is not done. Validate with tests/build/lint and/or a reliable manual repro.
- **Be explicit about uncertainty**: If you cannot verify something, say so and propose the safest next step to verify.

---

## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for any non-trivial task (3+ steps, multi-file change, architectural decision, production-impacting behavior).
- Include verification steps in the plan (not as an afterthought).
- If new information invalidates the plan: **stop**, update the plan, then continue.
- Write a crisp spec first when requirements are ambiguous (inputs/outputs, edge cases, success criteria).

### 2. Subagent Strategy (Parallelize Intelligently)
- Use subagents to keep the main context clean and to parallelize:
- repo exploration, pattern discovery, test failure triage, dependency research, risk review.
- Give each subagent **one focused objective** and a concrete deliverable:
- "Find where X is implemented and list files + key functions" beats "look around."
- Merge subagent outputs into a short, actionable synthesis before coding.

### 3. Incremental Delivery (Reduce Risk)
- Prefer **thin vertical slices** over big-bang changes.
- Land work in small, verifiable increments:
- implement → test → verify → then expand.
- When feasible, keep changes behind:
- feature flags, config switches, or safe defaults.

### 4. Self-Improvement Loop
- After any user correction or a discovered mistake:
- add a new entry to `tasks/lessons.md` capturing:
- the failure mode, the detection signal, and a prevention rule.
- Review `tasks/lessons.md` at session start and before major refactors.

### 5. Verification Before "Done"
- Never mark complete without evidence:
- tests, lint/typecheck, build, logs, or a deterministic manual repro.
- Compare behavior baseline vs changed behavior when relevant.
- Ask: "Would a staff engineer approve this diff and the verification story?"

### 6. Demand Elegance (Balanced)
- For non-trivial changes, pause and ask:
- "Is there a simpler structure with fewer moving parts?"
- If the fix is hacky, rewrite it the elegant way **if** it does not expand scope materially.
- Do not over-engineer simple fixes; keep momentum and clarity.

### 7. Autonomous Bug Fixing (With Guardrails)
- When given a bug report:
- reproduce → isolate root cause → fix → add regression coverage → verify.
- Do not offload debugging work to the user unless truly blocked.
- If blocked, ask for **one** missing detail with a recommended default and explain what changes based on the answer.

---

## Task Management (File-Based, Auditable)

1. **Plan First**
- Write a checklist to `tasks/todo.md` for any non-trivial work.
- Include "Verify" tasks explicitly (lint/tests/build/manual checks).
2. **Define Success**
- Add acceptance criteria (what must be true when done).
3. **Track Progress**
- Mark items complete as you go; keep one "in progress" item at a time.
4. **Checkpoint Notes**
- Capture discoveries, decisions, and constraints as you learn them.
5. **Document Results**
- Add a short "Results" section: what changed, where, how verified.
6. **Capture Lessons**
- Update `tasks/lessons.md` after corrections or postmortems.

---

## Communication Guidelines (User-Facing)

### 1. Be Concise, High-Signal
- Lead with outcome and impact, not process.
- Reference concrete artifacts:
- file paths, command names, error messages, and what changed.
- Avoid dumping large logs; summarize and point to where evidence lives.

### 2. Ask Questions Only When Blocked
When you must ask:
- Ask **exactly one** targeted question.
- Provide a recommended default.
- State what would change depending on the answer.

### 3. State Assumptions and Constraints
- If you inferred requirements, list them briefly.
- If you could not run verification, say why and how to verify.

### 4. Show the Verification Story
- Always include:
- what you ran (tests/lint/build), and the outcome.
- If you didn't run something, give a minimal command list the user can run.

### 5. Avoid "Busywork Updates"
- Don't narrate every step.
- Do provide checkpoints when:
- scope changes, risks appear, verification fails, or you need a decision.

---

## Context Management Strategies (Don't Drown the Session)

### 1. Read Before Write
- Before editing:
- locate the authoritative source of truth (existing module/pattern/tests).
- Prefer small, local reads (targeted files) over scanning the whole repo.

### 2. Keep a Working Memory
- Maintain a short running "Working Notes" section in `tasks/todo.md`:
- key constraints, invariants, decisions, and discovered pitfalls.
- When context gets large:
- compress into a brief summary and discard raw noise.

### 3. Minimize Cognitive Load in Code
- Prefer explicit names and direct control flow.
- Avoid clever meta-programming unless the project already uses it.
- Leave code easier to read than you found it.

### 4. Control Scope Creep
- If a change reveals deeper issues:
- fix only what is necessary for correctness/safety.
- log follow-ups as TODOs/issues rather than expanding the current task.

---

## Error Handling and Recovery Patterns

### 1. "Stop-the-Line" Rule
If anything unexpected happens (test failures, build errors, behavior regressions):
- stop adding features
- preserve evidence (error output, repro steps)
- return to diagnosis and re-plan

### 2. Triage Checklist (Use in Order)
1. **Reproduce** reliably (test, script, or minimal steps).
2. **Localize** the failure (which layer: UI, API, DB, network, build tooling).
3. **Reduce** to a minimal failing case (smaller input, fewer steps).
4. **Fix** root cause (not symptoms).
5. **Guard** with regression coverage (test or invariant checks).
6. **Verify** end-to-end for the original report.

### 3. Safe Fallbacks (When Under Time Pressure)
- Prefer "safe default + warning" over partial behavior.
- Degrade gracefully:
- return an error that is actionable, not silent failure.
- Avoid broad refactors as "fixes."

### 4. Rollback Strategy (When Risk Is High)
- Keep changes reversible:
- feature flag, config gating, or isolated commits.
- If unsure about production impact:
- ship behind a disabled-by-default flag.

### 5. Instrumentation as a Tool (Not a Crutch)
- Add logging/metrics only when they:
- materially reduce debugging time, or prevent recurrence.
- Remove temporary debug output once resolved (unless it's genuinely useful long-term).

---

## Engineering Best Practices (AI Agent Edition)

### 1. API / Interface Discipline
- Design boundaries around stable interfaces:
- functions, modules, components, route handlers.
- Prefer adding optional parameters over duplicating code paths.
- Keep error semantics consistent (throw vs return error vs empty result).

### 2. Testing Strategy
- Add the smallest test that would have caught the bug.
- Prefer:
- unit tests for pure logic,
- integration tests for DB/network boundaries,
- E2E only for critical user flows.
- Avoid brittle tests tied to incidental implementation details.

### 3. Type Safety and Invariants
- Avoid suppressions (`any`, ignores) unless the project explicitly permits and you have no alternative.
- Encode invariants where they belong:
- validation at boundaries, not scattered checks.

### 4. Dependency Discipline
- Do not add new dependencies unless:
- the existing stack cannot solve it cleanly, and the benefit is clear.
- Prefer standard library / existing utilities.

### 5. Security and Privacy
- Never introduce secret material into code, logs, or chat output.
- Treat user input as untrusted:
- validate, sanitize, and constrain.
- Prefer least privilege (especially for DB access and server-side actions).

### 6. Performance (Pragmatic)
- Avoid premature optimization.
- Do fix:
- obvious N+1 patterns, accidental unbounded loops, repeated heavy computation.
- Measure when in doubt; don't guess.

### 7. Accessibility and UX (When UI Changes)
- Keyboard navigation, focus management, readable contrast, and meaningful empty/error states.
- Prefer clear copy and predictable interactions over fancy effects.

### 8. Logging Convention

| Layer | Tool | Level |
|-------|------|-------|
| CLI user output | `click.echo()` / `console.print()` | N/A |
| Operational flow events | `logger.info` | Start, complete, skip |
| Recoverable failures | `logger.warning` | Retries, fallbacks, degradation |
| Unrecoverable errors | `logger.error` | Failures that affect output |
| Debug diagnostics | `logger.debug` | Exception traces, internal state |

Rules:
- Business logic: `logger = logging.getLogger(__name__)` — never `print()`
- CLI: `click.echo()` for user output, `logger.*` for operational logging
- Silent `except: pass` must log at `debug` or `warning` (except destructors and safety utilities)
- `print()` permitted only in: standalone scripts (`__main__`), docstring examples, dedicated debug handlers

---

## Git and Change Hygiene (If Applicable)

- Keep commits atomic and describable; avoid "misc fixes" bundles.
- Don't rewrite history unless explicitly requested.
- Don't mix formatting-only changes with behavioral changes unless the repo standard requires it.
- Treat generated files carefully:
- only commit them if the project expects it.

---

## Definition of Done (DoD)

A task is done when:
- Behavior matches acceptance criteria.
- Tests/lint/typecheck/build (as relevant) pass or you have a documented reason they were not run.
- Risky changes have a rollback/flag strategy (when applicable).
- The code follows existing conventions and is readable.
- A short verification story exists: "what changed + how we know it works."

---

## Templates

### Plan Template (Paste into `tasks/todo.md`)
- [ ] Restate goal + acceptance criteria
- [ ] Locate existing implementation / patterns
- [ ] Design: minimal approach + key decisions
- [ ] Implement smallest safe slice
- [ ] Add/adjust tests
- [ ] Run verification (lint/tests/build/manual repro)
- [ ] Summarize changes + verification story
- [ ] Record lessons (if any)

### Bugfix Template (Use for Reports)
- Repro steps:
- Expected vs actual:
- Root cause:
- Fix:
- Regression coverage:
- Verification performed:
- Risk/rollback notes: