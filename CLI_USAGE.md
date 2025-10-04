# Agent Actions CLI Usage Guide

## Running Commands from Subdirectories

Agent Actions CLI commands automatically detect your project root, allowing you to run commands from any subdirectory within your project—just like git, dbt, and npm.

### How It Works

The CLI searches for `agent_actions.yml` by walking up the directory tree from your current location:

1. Checks current directory for `agent_actions.yml`
2. If not found, checks parent directory
3. Continues up to filesystem root or finds project file
4. Uses the first `agent_actions.yml` found (nearest ancestor)

When a project is found, the CLI:
- Changes to the project root directory
- Executes your command
- Restores your original directory when done

This ensures all relative paths in your configuration work correctly, regardless of where you run the command from.

---

## Examples

### Basic Usage

```bash
# Project structure
my-project/
├── agent_actions.yml       # Project root marker
├── src/
│   ├── agents/
│   └── utils/
└── tests/

# All of these work the same:

# From project root
cd my-project
agent-actions run -a my_agent
# 📁 Project root: .
# ✅ Running workflow...

# From subdirectory (2 levels deep)
cd my-project/src/utils
agent-actions run -a my_agent
# 📁 Project root: ../..
# ✅ Running workflow...

# From deep subdirectory (4+ levels)
cd my-project/src/agents/helpers/validators
agent-actions run -a my_agent
# 📁 Project root: ../../../../
# ✅ Running workflow...
```

### Multiple Commands

All project-aware commands work from any subdirectory:

```bash
cd my-project/src

# Run workflow
agent-actions run -a my_agent
# 📁 Project root: ..

# Clean artifacts
agent-actions clean -a my_agent -f
# 📁 Project root: ..

# Check status
agent-actions status -a my_agent
# 📁 Project root: ..

# Render templates
agent-actions render -a my_agent
# 📁 Project root: ..

# Generate docs
agent-actions docs
# 📁 Project root: ..
```

---

## Commands That Work From Anywhere in Project

The following commands automatically find your project root:

| Command | Description |
|---------|-------------|
| `run` | Execute agent workflows |
| `clean` | Clean artifacts and temporary files |
| `status` | Check workflow status |
| `render` | Render agent templates |
| `docs` | Generate/serve documentation |
| `batch status` | Check batch job status |
| `batch retrieve` | Retrieve batch results |

---

## Commands That Work Outside Projects

These commands don't require being in a project:

| Command | Description |
|---------|-------------|
| `init` | Create a new project |
| `--version` | Show version information |
| `--help` | Display help message |

---

## Error Handling

### Not in a Project

If you try to run a project command outside any project, you'll get a helpful error message:

```bash
$ cd /tmp
$ agent-actions run -a my_agent

Error: Not in an agent-actions project

Could not find 'agent_actions.yml' in current directory or any parent directory.

Current directory: /tmp

Solutions:
  1. Navigate to your agent-actions project directory
  2. Run 'agent-actions init' to create a new project
```

The error message:
- ✅ Clearly states the problem
- ✅ Shows where you currently are
- ✅ Provides actionable solutions
- ✅ Uses color (red "Error:") for visibility

---

## Advanced Features

### Nested Projects

If you have nested projects (e.g., git submodules), agent-actions uses the **nearest** `agent_actions.yml`:

```bash
outer-project/
├── agent_actions.yml          # Outer project config
└── submodule/
    ├── agent_actions.yml      # Inner project config
    └── src/
        └── utils/

# From outer project
cd outer-project
agent-actions run -a my_agent
# Uses: outer-project/agent_actions.yml

# From inner project
cd outer-project/submodule/src/utils
agent-actions run -a my_agent
# Uses: outer-project/submodule/agent_actions.yml (nearest ancestor)
```

**Best Practice:** Each project uses its own configuration independently.

### Symlinks

Symlinks are resolved automatically to their real paths:

```bash
# Create symlink to project subdirectory
ln -s /projects/my-project/src /tmp/my-link

# Run from symlink
cd /tmp/my-link
agent-actions run -a test

# ✅ Resolves symlink to: /projects/my-project/src
# ✅ Finds project root: /projects/my-project
# ✅ Uses: /projects/my-project/agent_actions.yml
```

### Deep Directory Nesting

The CLI can find your project root from any depth (up to 100 levels):

```bash
# Even from very deeply nested directories
cd my-project/a/b/c/d/e/f/g/h
agent-actions run -a test
# 📁 Project root: ../../../../../../../../
# ✅ Works correctly
```

---

## Benefits

### ✅ Better Developer Experience

No need to remember or navigate to project root before running commands:

```bash
# Before (annoying)
cd /path/to/project/src/utils
cd ../..  # Navigate to root
agent-actions run -a my_agent
cd src/utils  # Navigate back

# Now (seamless)
cd /path/to/project/src/utils
agent-actions run -a my_agent  # Just works!
```

### ✅ IDE/Editor Integration

Works from any directory you're editing in:

- Open file in `src/agents/my_agent.py`
- Run command from editor's terminal
- No need to change directories first

### ✅ Consistent with Familiar Tools

Matches behavior you already know from:

| Tool | Marker File | Behavior |
|------|-------------|----------|
| **git** | `.git/` directory | Works from any subdirectory |
| **dbt** | `dbt_project.yml` | Finds project by walking up tree |
| **npm** | `package.json` | Commands work from any subdirectory |
| **agent-actions** | `agent_actions.yml` | ✅ Same behavior |

### ✅ Clear Feedback

Always know which project root was detected:

```bash
📁 Project root: .          # At root
📁 Project root: ..         # One level down
📁 Project root: ../..      # Two levels down
📁 Project root: /absolute/path  # Outside current directory
```

---

## Troubleshooting

### Problem: Command says "Not in an agent-actions project" but I'm in my project

**Diagnosis:**

Check that `agent_actions.yml` exists in your project root:

```bash
# Find all agent_actions.yml files
find . -name "agent_actions.yml" -type f

# Check if project root has the file
ls -la /path/to/project/agent_actions.yml

# Check current directory and parents
pwd && ls -la agent_actions.yml
cd .. && ls -la agent_actions.yml
```

**Common causes:**
- File is named `agent_actions.yaml` (wrong extension - use `.yml`)
- File is in wrong directory (not at project root)
- Typo in filename
- File doesn't have read permissions

**Solution:**

Ensure you have `agent_actions.yml` at your project root:

```bash
cd /path/to/your/project
ls -la agent_actions.yml  # Should exist

# If missing, create it
agent-actions init --name my_project
```

---

### Problem: Using wrong project in nested structure

**Diagnosis:**

The CLI uses the *nearest* `agent_actions.yml`. If you have nested projects:

```bash
outer/
├── agent_actions.yml      # Outer config
└── inner/
    ├── agent_actions.yml  # Inner config
    └── src/
```

Commands run from `outer/inner/src/` will use `inner/agent_actions.yml`.

**Solution:**

To use the outer project, run from outside the inner project directory:

```bash
# Use inner project
cd outer/inner/src
agent-actions run -a test  # Uses: outer/inner/agent_actions.yml

# Use outer project
cd outer/src
agent-actions run -a test  # Uses: outer/agent_actions.yml
```

---

### Problem: Symlink confusion

**Diagnosis:**

Symlinks can make directory paths confusing. The CLI resolves symlinks to real paths.

**Example:**

```bash
# Real structure
/projects/my-project/src/

# Symlink
/tmp/link -> /projects/my-project/src/

# From symlink
cd /tmp/link
pwd  # Shows: /tmp/link
agent-actions run -a test
# Resolves to: /projects/my-project/src/
# Finds: /projects/my-project/agent_actions.yml
```

**Solution:**

The CLI handles this automatically. If confused, check the real path:

```bash
# See real path
pwd -P
readlink -f .
```

---

## FAQ

**Q: Can I disable project root detection?**

A: No, but commands that don't need projects (`init`, `--version`, `--help`) work anywhere.

**Q: How deep can my directory structure be?**

A: The CLI searches up to 100 parent directories. This is more than enough for any real project.

**Q: Does this work on Windows?**

A: Yes! The implementation uses `pathlib.Path` for cross-platform compatibility.

**Q: What if I have multiple `agent_actions.yml` files?**

A: The CLI uses the **nearest** one (first found walking up from current directory).

**Q: Can I see verbose output of project root detection?**

A: The CLI shows `📁 Project root: <path>` for each command. For debugging, use `--debug` flag.

**Q: Does this slow down commands?**

A: No. Project root detection is very fast (just filesystem stat calls). Overhead is negligible.

---

## Summary

✅ **Works from any subdirectory** - Run commands from wherever you're working

✅ **Automatic detection** - Finds `agent_actions.yml` by walking up directory tree

✅ **Clear feedback** - Always shows which project root was detected

✅ **Handles edge cases** - Nested projects, symlinks, deep nesting

✅ **Helpful errors** - Clear guidance when not in a project

✅ **Familiar behavior** - Matches git, dbt, npm workflows

---

For more information, see:
- [CHANGELOG.md](CHANGELOG.md) - Release notes and change history
- [Issue #422](https://github.com/Muizzkolapo/agent-actions/issues/422) - Original feature request
- [Manual Testing Checklist](dev_artefacts/manual_testing/issue_422_checklist.md) - Test scenarios
