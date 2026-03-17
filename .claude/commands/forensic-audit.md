# Forensic Audit — Generic

Run a full forensic audit of a target directory. Pass the target path and optional context as arguments.

**Usage:** `/forensic-audit docs.agent-actions` or `/forensic-audit editors/vscode "focus on extension activation and LSP"`

---

## Input

**Target:** $ARGUMENTS

Parse the first token as the target directory path (relative to repo root). Any remaining text is additional context or focus areas for the audit.

If no arguments are provided, ask the user which directory to audit.

## Your Role

You are a principal-level software engineer performing a zero-shortcut forensic audit of the target directory. Your job is to find real bugs, architectural risks, and maintainability debt — not to write code. You will produce a single structured report.

## Ground Rules

1. **Read before you judge.** Read every first-party source file before making claims. Use any manifest, README, or index file in the target for navigation.
2. **Reproduce or qualify.** For every finding, either reproduce it with a concrete command/script or explicitly mark it as "not reproduced — high confidence based on code inspection."
3. **No false positives.** Only report issues you can point to with file paths and line numbers. Do not report stylistic preferences or hypothetical risks without evidence.
4. **Cross-reference prior work.** Read `tasks/todo.md` (if it exists) to understand what has already been fixed. Do not re-report addressed issues.
5. **One report, one file.** Write your full report to `FORENSIC_AUDIT_<TARGET_NAME>.md` at the repo root (e.g., `FORENSIC_AUDIT_DOCS.md`). Do not scatter findings across multiple files.
6. **Do not modify production code.** This is an audit, not a fix. You may create small throwaway scripts to reproduce bugs, but do not commit them.

## Phase 0 — Auto-Detect Stack

Before starting, identify the technology stack of the target directory:

- [ ] List all file extensions and count them (e.g., `.ts`: 45, `.css`: 12, `.py`: 3)
- [ ] Identify the primary language(s) and framework(s)
- [ ] Locate the package manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, etc.)
- [ ] Identify the build/test/lint toolchain from the manifest and any config files
- [ ] Identify the entry point(s) (e.g., `main.ts`, `app/layout.tsx`, `__main__.py`, `docusaurus.config.ts`)

Record this as a "Stack Profile" at the top of your working notes. All subsequent verification commands should use the detected toolchain.

## Scope

### In Scope
- All first-party source files in the target directory
- All tests associated with the target (look for `tests/`, `__tests__/`, `*.test.*`, `*.spec.*`, `test_*`)
- Configuration files that affect runtime behavior (build configs, framework configs, CI)
- Static assets that affect correctness (CSS, HTML templates, SVGs referenced in code)
- Documentation/content files if the target is a docs site

### Out of Scope (skim only)
- Generated/vendored assets: `node_modules/`, `_next/`, `.venv/`, `dist/`, `build/`, lockfiles
- Binary assets (images, fonts) unless referenced incorrectly in code
- Third-party code and dependencies (audit the usage, not the library)

## Execution Checklist

### Phase 1 — Orientation
- [ ] Read any README, CLAUDE.md, or manifest files in the target directory
- [ ] Read `tasks/todo.md` (if present) for completed/open work
- [ ] Read any prior audit reports (if present)
- [ ] Build a mental map of the directory structure

### Phase 2 — Inventory
- [ ] Count all source files by type
- [ ] Identify the largest files by LOC (flag anything >400 LOC for review)
- [ ] Identify hub modules with highest fan-in (most importers/dependents)
- [ ] Map the dependency graph between major modules/components

### Phase 3 — Verification Commands
Run the appropriate commands for the detected stack and record exact output:

**For any stack:**
- [ ] Build/compile — does it succeed without errors?
- [ ] Lint — run the project's configured linter
- [ ] Type check — run the project's type checker (if configured)
- [ ] Tests — run the test suite, record pass/fail/skip counts

**Stack-specific examples (adapt to what you find):**

| Stack | Build | Lint | Types | Tests |
|-------|-------|------|-------|-------|
| Node/TS | `npm run build` | `npx eslint .` | `npx tsc --noEmit` | `npm test` |
| Python | `python -m py_compile` | `ruff check .` | `mypy <pkg>` | `pytest -q` |
| Docusaurus | `npm run build` | `npx eslint .` | `npx tsc --noEmit` | (Playwright if configured) |
| Rust | `cargo build` | `cargo clippy` | (included in build) | `cargo test` |
| Go | `go build ./...` | `golangci-lint run` | (included in build) | `go test ./...` |

### Phase 4 — Deep Read

Read every first-party source file. For each module/component, look for:

**Correctness:**
- Runtime errors (uncaught exceptions, null/undefined access, type mismatches)
- Logic bugs (wrong return value, off-by-one, incorrect conditions)
- State management issues (stale state, race conditions, memory leaks)
- Silent failures (swallowed errors, missing error propagation)
- Data/content integrity (broken links, missing assets, contract drift)

**Safety:**
- Type safety bypasses (`any`, `as unknown as`, `# type: ignore`, suppressions)
- Input validation gaps (untrusted input reaching dangerous operations)
- Secret/credential exposure in code, logs, or config
- XSS, injection, or other OWASP risks in web-facing code

**Architecture:**
- God modules (>400 LOC, high fan-out, multiple responsibilities)
- Circular or tightly-coupled dependencies
- Global mutable state
- Duplicated logic (same algorithm in multiple places)
- Contract drift (docs/types/schemas say one thing, code does another)
- Dead code (exports never imported, functions never called, unreachable branches)

**For docs/content sites specifically:**
- Broken internal links or anchors
- Inconsistent styling between light/dark themes
- Missing or incorrect metadata (frontmatter, SEO, accessibility)
- Content that contradicts the actual codebase behavior
- Build warnings that indicate content issues

**Testing:**
- Coverage blind spots (critical paths with no test coverage)
- False-confidence tests (always pass, mock everything, test implementation details)
- Missing regression tests for known issues

### Phase 5 — Targeted Reproduction
For the most impactful findings (especially P0 defects), write a minimal reproduction and record whether it succeeded or failed.

### Phase 6 — Dependency Analysis
- [ ] Identify the top 10 most-imported/used modules
- [ ] Check for deprecated or unmaintained dependencies
- [ ] Look for version pins that may block upgrades
- [ ] Check for unnecessary dependencies (installed but unused)

## Report Format

Write your report to `FORENSIC_AUDIT_<TARGET_NAME>.md` using this structure:

```markdown
# Forensic Audit Report — <Target Name>

**Date:** YYYY-MM-DD
**Auditor:** [agent name/model]
**Target:** <directory path>
**Stack:** <language(s)> / <framework(s)> / <build tool(s)>
**Scope:** N source files, ~N LOC
**Prior work reviewed:** [list any todo.md or prior audits consulted]

---

## Stack Profile

| Attribute | Value |
|-----------|-------|
| Primary language | |
| Framework | |
| Build tool | |
| Test runner | |
| Linter | |
| Type checker | |
| Package manager | |

---

## Verification Summary

| Check | Command | Result | Notes |
|-------|---------|--------|-------|
| Build | `...` | pass/fail | |
| Lint | `...` | pass/fail | |
| Types | `...` | pass/fail | |
| Tests | `...` | N passed, N failed | |

---

## Findings

### P0 — Verified Defects
(Bugs that crash, corrupt data, or produce wrong results. Must include reproduction.)

#### [N]. [Short title]
- **File:** `path/to/file:LINE`
- **Reproduced:** Yes / No (high confidence)
- **Evidence:** [What you observed]
- **Root cause:** [Why it happens]
- **Impact:** [What breaks for users]
- **Suggested fix direction:** [1-2 sentences]

### P1 — Safety / Correctness Risks
(Issues likely to cause bugs under realistic conditions.)

### P2 — Architecture / Structural Debt
(Maintainability issues that slow development or increase bug risk.)

### P3 — Polish / Low Priority
(Nice-to-haves, minor drift, low-impact improvements.)

---

## Module Scorecard

| Module/Component | Score (1-10) | Key Concern |
|-----------------|-------------|-------------|
| ... | ... | ... |

---

## Final Verdict

[2-3 sentences: Overall health assessment. Top 3 things to fix first.]
```

## Quality Checklist

Before submitting, verify:
- [ ] Every finding has a file path and line number
- [ ] Every P0 finding has a reproduction command and observed output
- [ ] No finding duplicates something already marked done in prior work
- [ ] Findings are ordered by severity, not discovery order
- [ ] The verification summary includes actual command output, not just "passed"
- [ ] The module scorecard covers every major component in the target
- [ ] The report is a single file at the repo root

## Common Pitfalls

1. **Don't skim.** Read every file. The worst bugs hide in modules you'd skip.
2. **Don't report style opinions.** "I prefer X over Y" is not a finding. "X causes bug Z" is.
3. **Don't re-report fixed issues.** Always check prior work first.
4. **Don't modify production code.** Audit only.
5. **Don't skip verification commands.** Run them and record output even if you think they'll pass.
6. **Don't assume the stack.** Auto-detect it in Phase 0. A "docs site" might be Next.js, Docusaurus, Hugo, or plain HTML.
7. **Don't ignore the content.** For docs sites, broken links and content drift are P1-level findings.
