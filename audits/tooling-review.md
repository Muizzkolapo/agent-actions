# Code Review: agent_actions/tooling/

**Date:** 2026-06-17
**Reviewer:** Claude (single-angle deep review)
**Files reviewed:** 21 Python files

---

## Findings

### 1. CONFIRMED — RunTracker json.load crash on corrupted runs.json

- **File:** `agent_actions/tooling/docs/run_tracker.py:301,340`
- **Summary:** record_action_start and record_action_complete call json.load bare. @retry only catches LockException. JSONDecodeError from corrupted file crashes live workflow. Fix pattern already exists in start_workflow_run (line 244) which has try/except (OSError, JSONDecodeError).
- **Failure scenario:** Previous run interrupted mid-write → runs.json corrupted → next run calls record_action_start → JSONDecodeError → workflow thread crashes.
- **Severity:** HIGH — unhandled exception crashes live workflow

### 2. CONFIRMED — code_scanner.py missing OSError catch on file read

- **File:** `agent_actions/tooling/code_scanner.py:40`
- **Summary:** scan_tool_functions catches SyntaxError and UnicodeDecodeError but not OSError. Broken symlink or deleted file between rglob and read_text crashes generate_docs.
- **Severity:** MEDIUM — unhandled exception aborts docs generation

### 3. CONFIRMED — shutil.copy2 failure aborts entire catalog generation

- **File:** `agent_actions/tooling/docs/generator.py:62`
- **Summary:** No try/except around image copy. Disk-full or permission error on one image aborts full generate_docs, leaving catalog.json unwritten.
- **Severity:** MEDIUM — one bad image kills all docs

### 4. CONFIRMED — Naive substring replacement corrupts image URLs

- **File:** `agent_actions/tooling/docs/generator.py:69`
- **Summary:** `content.replace(old_path, new_path)` — 'logo.png' matches inside 'dark/logo.png'. Two images sharing a filename suffix produce broken URLs in catalog.
- **Failure scenario:** README with logo.png and dark/logo.png → first replace corrupts second path → both image links broken in rendered docs.
- **Severity:** MEDIUM — broken documentation images

### 5. CONFIRMED — Framework jargon in LSP diagnostic messages

- **Files:** `agent_actions/tooling/lsp/diagnostics.py:75,90,117` and `server.py:557`
- **Summary:** User-facing IDE diagnostics use internal terms: "context_scope reference", "Variables derived from context_scope.observe". Users never author these terms in their YAML.
- **Severity:** LOW — poor UX in editor

### 6. CONFIRMED — Dead ActionDefinition dataclass

- **File:** `agent_actions/tooling/lsp/models.py:57`
- **Summary:** Never imported or used anywhere. Superseded by ActionMetadata. Creates confusion for new contributors.
- **Severity:** LOW — dead code

---

## Recommended fix priority

| Priority | Findings | Effort |
|----------|----------|--------|
| P0 (crash) | #1 (RunTracker json.load) | Small — add try/except like start_workflow_run |
| P1 (robustness) | #2 (OSError), #3 (shutil.copy2) | Small — add exception guards |
| P1 (correctness) | #4 (substring replacement) | Small — longest-first or regex |
| P2 (UX) | #5 (jargon) | Small — rewrite messages |
| P3 (dead code) | #6 | Tiny — delete |
