# Agent Manifest Protocol (AMP)

**Status:** Version 1.0 (Draft)
**Target:** AI Agents & LLM-assisted Developers
**Goal:** Optimizing Codebase Navigation, Safety, and Refactoring Context through Well-Architected Metadata.

---

## 1. Executive Summary
The Agent Manifest Protocol (AMP) is a standard for creating self-documenting codebases optimized for AI consumption. By generating hierarchical metadata files (`_MANIFEST.md`) in every directory, we enable agents to practice **progressive disclosure**—navigating complex projects by reading high-level maps rather than consuming raw file tokens.

This protocol addresses the "Context vs. Cost" trade-off in Large Language Model (LLM) engineering, ensuring that agents act with the precision of a senior architect while maintaining the token efficiency of a junior developer.

## 2. The Well-Architected Context Framework
To ensure robustness, AMP is designed around six architectural pillars inspired by the AWS Well-Architected Framework:

### 2.1 Operational Excellence
*   **Infrastructure as Code:** Manifests are not written by humans; they are generated artifacts derived from the Abstract Syntax Tree (AST).
*   **Observability:** The manifest provides an immediate, high-level dashboard of the codebase's current state, surfacing structural complexity without needing a build step.

### 2.2 Security
*   **Data Minimization:** Manifests strictly contain *structural metadata* (symbols, docstrings, imports). They never contain variable values, secrets, or business logic implementation details.
*   **Least Privilege Context:** Agents only access the manifest relevant to their current directory scope, preventing "context pollution" from unrelated sensitive modules.

### 2.3 Reliability
*   **Change Management:** The "Signals" system acts as an early warning system for dependency management, preventing agents from introducing circular dependencies or breaking architectural boundaries.
*   **Self-Healing:** The generation script acts as a linter; if the code is unparsable, the manifest fails to generate, signaling immediate code health issues.

### 2.4 Performance Efficiency
*   **Token Optimization:** By using a linked graph of small Markdown files, AMP reduces the context window requirement by 90%+ compared to "read all files" strategies.
*   **Latency Reduction:** Agents can locate a target function in 2-3 hops (Root -> Submodule -> File) rather than searching the entire file system.

### 2.5 Cost Optimization
*   **Inference Cost:** Lower token usage directly correlates to lower inference costs per task.
*   **Rework Reduction:** By exposing dependencies ("Signals") upfront, agents are less likely to write code that fails integration tests, saving retry cycles.

### 2.6 Sustainability
*   **Energy Efficiency:** Reduced computation (tokens) means less energy consumed per coding task.

---

## 3. Integration with AGENTS.md
The Agent Manifest Protocol is designed to work in tandem with the **[AGENTS.md](https://agents.md/)** standard.

While `AGENTS.md` provides the **static, instructional context** (The "Why" and "How-To"), the AMP `_MANIFEST.md` provides the **dynamic, structural context** (The "What" and "Where").

### 3.1 The Context Hierarchy
*   **Parent (`AGENTS.md`):** Contains human-authored, high-level directives.
    *   *Content:* Build commands, testing protocols, code style guidelines, architectural vision.
    *   *Role:* "Read me first to understand *how* to behave."
*   **Child (`_MANIFEST.md`):** Contains machine-generated, low-level maps.
    *   *Content:* File lists, symbol trees, dependency signals.
    *   *Role:* "Read me next to navigate to *where* you need to work."

### 3.2 Linking Strategy
The root `AGENTS.md` must explicitly point to the root manifest.

**Example `AGENTS.md` snippet:**
```markdown
# Agent Context

## Project Structure
This project uses the Agent Manifest Protocol (AMP) for navigation.
**[> Open Codebase Map (_MANIFEST.md)](./_MANIFEST.md)**
```

---

## 4. The Manifest Standard (`_MANIFEST.md`)
The core artifact of AMP is the `_MANIFEST.md` file, auto-generated in every source directory.

### 4.1 File Structure
A manifest contains three standard sections:

#### A. Header (Identity)
The directory name and a high-level summary derived from the package documentation (e.g., `__init__.py` docstring, `package.json` description).

#### B. Sub-Modules (Navigation Edge)
A table linking to the `_MANIFEST.md` of immediate sub-directories.

| Sub-Module | Description |
|------------|-------------|
| `[cli](cli/_MANIFEST.md)` | Command-line interface entry points. |
| `[core](core/_MANIFEST.md)` | Core business logic. |

#### C. Files & Symbols (Content Node)
A detailed inventory of files in the current directory.

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `user_service.py` | Module | Handles user authentication. | `db`, `auth` |
| └─ `UserService` | Class | Main service class. | - |
| &nbsp;&nbsp;&nbsp;&nbsp;└─ `get_user` | Method | Retrieves user by ID. | - |

### 4.2 The "Signal" System
A **Signal** is a keyword derived from `import` statements that indicates a cross-module dependency.

*   **Derivation:** `import { Stripe } from '@lib/payments'` -> Signal: `payments`.
*   **Utility:** Signals act as "warning lights" for architectural boundaries.

---

## 5. Agent Workflows enabled by AMP

### 5.1 The Navigation Algorithm (Progressive Disclosure)
1.  **Root Check:** Read `./_MANIFEST.md` (via link in `AGENTS.md`).
2.  **Pathfinding:** Identify relevant sub-modules from the "Sub-Modules" table.
3.  **Traverse:** Read `path/to/sub/_MANIFEST.md`.
4.  **Pinpoint:** Identify the specific file and symbol.
5.  **Contextualize:** Check the "Signals" column.
6.  **Action:** Read the actual source code file only when strictly necessary.

### 5.2 The Safe Refactoring Algorithm
1.  **Signal Check:** Agent reads the target file's row in the manifest.
2.  **Dependency Audit:** It sees signals: `['config', 'legacy-core']`.
3.  **Conflict Detection:** Agent realizes `legacy-core` dependencies cannot be moved to the `modern-api` folder.
4.  **Resolution:** Agent plans a refactor to decouple dependencies *before* the move.

---

## 6. Polyglot Implementation Strategy
AMP is language-agnostic. The generator relies on **Abstract Syntax Trees (AST)** to extract summaries, symbols, and signals.

**Recommended Tooling: Tree-sitter**
Tree-sitter provides a unified parsing interface for Python, TypeScript, Go, Rust, Java, and C++.

### 6.1 Implementation Roadmap
*   **Python:** Implemented using `ast` module (Current).
*   **JavaScript/TypeScript:** Implement using `tree-sitter-typescript` bindings.
*   **Go:** Implement using `tree-sitter-go`.
*   **Rust:** Implement using `tree-sitter-rust`.

---

## 7. Governance & Automation
To maintain Operational Excellence, the manifest generation must be automated.

*   **Hook:** A `pre-commit` hook runs the generator script.
*   **CI Check:** The CI pipeline runs the generator and fails if the checked-in `_MANIFEST.md` differs from the generated one (ensuring no drift).
*   **Read-Only:** Developers should be instructed via `AGENTS.md` not to edit manifests manually.