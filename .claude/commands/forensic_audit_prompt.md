# Forensic Codebase Audit — Reusable Prompt

Copy everything below the line and give it to any AI coding agent (Claude, Codex, etc.) to run a full forensic audit of this repository.

---

## Your Role

You are a principal-level software engineer performing a zero-shortcut forensic audit of this codebase. Your job is to find real bugs, architectural risks, and maintainability debt — not to write code. You will produce a single structured report file with severity-ordered, evidence-backed findings.

## Ground Rules

1. **Read before you judge.** Read every first-party Python file before making claims. Use the manifest chain (`agent_actions/_MANIFEST.md` and subdirectory manifests) for navigation.
2. **Reproduce or qualify.** For every finding, either reproduce it with a concrete command/script or explicitly mark it as "not reproduced — high confidence based on code inspection."
3. **No false positives.** Only report issues you can point to with file paths and line numbers. Do not report stylistic preferences or hypothetical risks without evidence.
4. **Cross-reference prior work.** Read `tasks/todo.md` to understand what has already been fixed. Do not re-report addressed issues. If a prior fix was incomplete, say so with evidence.
5. **One report, one file.** Write your full report to `FORENSIC_AUDIT_REPORT.md` at the repo root (this path is NOT gitignored). Do not scatter findings across multiple files.
6. **Do not modify production code.** This is an audit, not a fix. You may create small throwaway scripts to reproduce bugs, but do not commit them.

## Scope

### In Scope
- All first-party Python under `agent_actions/` (follow `_MANIFEST.md` chain)
- All tests under `tests/`
- Runtime-affecting configs: `pyproject.toml`, `pytest.ini`, `ruff.toml` (if present), `README.md`
- Example workflows, config schemas, and documentation under `docs.agent-actions/` (scan for contract drift)
- CI configuration (`.github/workflows/` if present)

### Out of Scope (skim only)
- Generated/vendored assets: `node_modules/`, `_next/static/`, `.venv/`, lockfiles, image assets
- Third-party code and editor plugins under `editors/`

## Execution Checklist

Follow these steps in order. Check each one off in your working notes.

### Phase 1 — Orientation
- [ ] Read `CLAUDE.md` and `AGENTS.md` (if present) for project conventions
- [ ] Read `tasks/todo.md` to understand completed and open work
- [ ] Read `tasks/forensic_audit_consolidated.md` (if present) for prior audit findings
- [ ] Read `agent_actions/_MANIFEST.md` and build a mental map of the package structure

### Phase 2 — Inventory
- [ ] Count all Python files under `agent_actions/` and `tests/` (use `find` or glob)
- [ ] Identify the largest files by LOC (flag anything >500 LOC as a candidate for review)
- [ ] Identify hub modules with highest fan-in (most importers)

### Phase 3 — Verification Commands
Run each command and record the exact output:
- [ ] `.venv/bin/pytest -q` — record pass/fail count and any warnings
- [ ] `.venv/bin/python -m ruff check .` — record result
- [ ] `.venv/bin/python -m mypy agent_actions` — record result and note any `ignore_errors` overrides in `pyproject.toml`
- [ ] `.venv/bin/pytest --cov=agent_actions --cov-report=term-missing -q` — record overall coverage and list modules below 50%

### Phase 4 — Deep Read (the actual audit)
Read every first-party Python module. For each package, look for:

**Correctness:**
- Runtime errors (NameError, AttributeError, TypeError at call sites)
- Logic bugs (wrong return value, off-by-one, incorrect condition)
- Race conditions (shared mutable state without locks, unsafe singleton init)
- Silent failures (broad `except` that swallows errors, missing error propagation)
- Data loss paths (write failures not propagated, false-success completion)

**Safety:**
- Type safety bypasses (`# type: ignore`, mypy `ignore_errors`, `Any` abuse)
- Input validation gaps (untrusted input reaching SQL, shell, or file operations)
- Secret/credential exposure in code, logs, or config
- Dependency vulnerabilities (deprecated packages, known CVEs)

**Architecture:**
- God modules (>500 LOC, high fan-out, multiple responsibilities)
- Circular or tightly-coupled imports
- Global mutable state (singletons, module-level dicts, `sys.path` mutation)
- Duplicated logic (same algorithm implemented in multiple places)
- Contract drift (docs/schemas say one thing, code does another)

**Testing:**
- Coverage blind spots (critical paths with low or no test coverage)
- False-confidence tests (tests that always pass, mock everything, or test implementation details)
- Missing regression tests for known bug fixes

### Phase 5 — Targeted Reproduction
For the most impactful findings (especially P0 runtime defects), write a minimal reproduction:
```bash
.venv/bin/python -c "from agent_actions.foo import bar; bar(edge_case_input)"
```
Record whether it succeeded or failed and the exact output.

### Phase 6 — Dependency Analysis
- [ ] Identify the top 10 most-imported modules (hub modules)
- [ ] Check for deprecated or unmaintained dependencies in `pyproject.toml`
- [ ] Look for version pins that may block upgrades

## Report Format

Write your report to `FORENSIC_AUDIT_REPORT.md` using exactly this structure:

```markdown
# Forensic Audit Report

**Date:** YYYY-MM-DD
**Auditor:** [agent name/model]
**Scope:** agent_actions/ (N files, ~N LOC) + tests/ (N files)
**Prior work reviewed:** tasks/todo.md, tasks/forensic_audit_consolidated.md

---

## Verification Summary

| Check | Command | Result | Notes |
|-------|---------|--------|-------|
| Tests | `.venv/bin/pytest -q` | N passed, N failed, N warnings | |
| Lint | `.venv/bin/python -m ruff check .` | pass/fail | |
| Types | `.venv/bin/python -m mypy agent_actions` | pass/fail | Note ignore_errors overrides |
| Coverage | `pytest --cov=agent_actions ...` | N% overall | List modules <50% |

---

## Findings

### P0 — Verified Runtime Defects
(Bugs that crash, corrupt data, or produce wrong results. Must include reproduction.)

#### [N]. [Short title]
- **File:** `path/to/file.py:LINE`
- **Reproduced:** Yes / No (high confidence)
- **Evidence:** [What you observed — error message, wrong output, etc.]
- **Root cause:** [Why it happens]
- **Impact:** [What breaks for users]
- **Suggested fix direction:** [1-2 sentences, not a full implementation]

### P1 — Safety / Correctness Risks
(Issues that are likely to cause bugs under realistic conditions.)

### P2 — Architecture / Structural Debt
(Maintainability issues that slow development or increase bug risk.)

### P3 — Polish / Low Priority
(Nice-to-haves, style issues with evidence, minor drift.)

---

## Already Addressed (Cross-Referenced with tasks/todo.md)

List findings you investigated but confirmed are already fixed, with the PR/task that fixed them.

---

## Package Scorecard

| Package | Score (1-10) | Key Concern |
|---------|-------------|-------------|
| errors | 8 | ... |
| config | 6 | ... |
| ... | ... | ... |

---

## Final Verdict

[2-3 sentences: Would you approve this codebase for production? What are the top 3 things to fix first?]
```

## Quality Checklist for Your Report

Before submitting, verify:
- [ ] Every finding has a file path and line number
- [ ] Every P0 finding has a reproduction command and observed output
- [ ] No finding duplicates something already marked done in `tasks/todo.md`
- [ ] Findings are ordered by severity, not by the order you discovered them
- [ ] The verification summary includes actual command output, not just "passed"
- [ ] The package scorecard covers every top-level package under `agent_actions/`
- [ ] The report is a single file at `FORENSIC_AUDIT_REPORT.md` (repo root)

## Common Pitfalls to Avoid

1. **Don't skim.** Read every file. The worst bugs hide in modules you'd skip.
2. **Don't report style opinions.** "I prefer X over Y" is not a finding. "X causes bug Z" is.
3. **Don't re-report fixed issues.** Always check `tasks/todo.md` first.
4. **Don't put the report in `tasks/`.** That directory is gitignored. Use repo root.
5. **Don't create multiple files.** One report, one file, one PR.
6. **Don't modify production code.** Audit only. Fixes come later.
7. **Don't skip verification commands.** Even if you think they'll pass, run them and record output.
8. **Don't count tests as coverage.** High test count with low coverage is a finding, not a positive.
