# Manual Testing Checklist - Issue #422: Project Root Detection

## Overview
This checklist verifies that CLI commands work from any subdirectory within a project (like git, dbt, npm).

**Feature:** Commands automatically detect project root by finding `agent_actions.yml`
**Issue:** https://github.com/Muizzkolapo/agent-actions/issues/422

---

## Test Setup

### Prerequisites
- [ ] Build/install latest version with issue #422 changes
- [ ] Have a test project ready (or create one below)

### Create Test Project
```bash
# Create test project structure
mkdir -p /tmp/test_project
cd /tmp/test_project

# Create agent_actions.yml (minimal config)
cat > agent_actions.yml << 'EOF'
# Test project config
model_vendor: anthropic
model_name: claude-3-5-sonnet-20241022
EOF

# Create subdirectories
mkdir -p src/utils
mkdir -p src/components/helpers
mkdir -p agents
mkdir -p a/b/c/d  # Deep nesting test
```

---

## Test Scenarios

### ✅ Scenario 1: Run from project root

**Test:**
```bash
cd /tmp/test_project
agent-actions run -a test_agent
```

**Expected:**
- Shows: `📁 Project root: .`
- Command attempts to execute (may fail if agent doesn't exist, that's OK)
- Does NOT show: "Not in an agent-actions project" error

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 2: Run from subdirectory (2 levels deep)

**Test:**
```bash
cd /tmp/test_project/src/utils
agent-actions run -a test_agent
```

**Expected:**
- Shows: `📁 Project root: ../..` or similar relative path
- Finds `agent_actions.yml` in ancestor directory
- Command attempts to execute

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 3: Run from deep subdirectory (4+ levels)

**Test:**
```bash
cd /tmp/test_project/a/b/c/d
agent-actions run -a test_agent
```

**Expected:**
- Shows: `📁 Project root: ../../../../` or similar
- Successfully finds project root
- Command attempts to execute

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 4: Run outside project (error handling)

**Test:**
```bash
cd /tmp
agent-actions run -a test_agent
```

**Expected:**
- Error message: `Error: Not in an agent-actions project`
- Message includes: `Could not find 'agent_actions.yml' in current directory or any parent directory`
- Shows current directory: `/tmp`
- Lists solutions:
  1. Navigate to your agent-actions project directory
  2. Run 'agent-actions init' to create a new project
- Exit code: 1 (error)

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 5: Init command works anywhere

**Test:**
```bash
cd /tmp/new_project
agent-actions init --name test_project
```

**Expected:**
- Command works (does NOT require being in a project)
- No "Not in an agent-actions project" error
- May prompt for input or show usage help

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 6: Version command works anywhere

**Test:**
```bash
cd /tmp
agent-actions --version
```

**Expected:**
- Shows version number
- No project root detection
- Exit code: 0

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 7: Multiple commands from subdirectory

**Test:**
```bash
cd /tmp/test_project/src

# Test different commands
agent-actions clean -a test_agent -f
agent-actions status -a test_agent
agent-actions render -a test_agent
agent-actions docs --help
```

**Expected:**
- All commands find project root
- Each shows: `📁 Project root: ..`
- All attempt to execute (may fail on missing agent, that's OK)

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 8: Nested projects (uses nearest ancestor)

**Setup:**
```bash
# Create outer project
mkdir -p /tmp/nested_test/outer
cd /tmp/nested_test/outer
echo "# Outer project" > agent_actions.yml

# Create inner project
mkdir -p inner/src
cd inner
echo "# Inner project" > agent_actions.yml
```

**Test:**
```bash
cd /tmp/nested_test/outer/inner/src
agent-actions run -a test
```

**Expected:**
- Finds inner `agent_actions.yml` (nearest ancestor)
- Shows: `📁 Project root: ..` (pointing to inner, not outer)
- Uses inner project config

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

### ✅ Scenario 9: Symlinks (resolves correctly)

**Setup:**
```bash
cd /tmp/test_project
ln -s src/utils /tmp/link_to_utils
```

**Test:**
```bash
cd /tmp/link_to_utils
agent-actions run -a test
```

**Expected:**
- Resolves symlink to real path
- Finds `agent_actions.yml` in real project root
- Command executes

**Actual:**
- [ ] Pass
- [ ] Fail
- Notes: _______________________________________________

---

## Cross-Platform Testing

### macOS
- [ ] All scenarios pass
- [ ] Notes: _______________________________________________

### Linux
- [ ] All scenarios pass
- [ ] Notes: _______________________________________________

### Windows
- [ ] All scenarios pass
- [ ] Notes: _______________________________________________

---

## Edge Cases (Optional)

### Very long path (100+ directory levels)
**Test:** Create deeply nested path and verify still works
- [ ] Pass
- [ ] Fail

### Permission errors
**Test:** Directory with restricted permissions in parent path
- [ ] Gracefully handles (skips inaccessible dirs)
- [ ] Notes: _______________________________________________

### Special characters in path
**Test:** Path with spaces, unicode, etc.
- [ ] Works correctly
- [ ] Notes: _______________________________________________

---

## Summary

**Date Tested:** _______________
**Tested By:** _______________
**Version:** _______________

**Results:**
- Total scenarios: 9 core scenarios
- Passed: ___ / 9
- Failed: ___ / 9

**Critical Issues Found:**
- _______________________________________________
- _______________________________________________

**Non-Critical Issues:**
- _______________________________________________
- _______________________________________________

**Overall Status:**
- [ ] ✅ Ready to merge (all scenarios pass)
- [ ] ⚠️ Needs fixes (some failures)
- [ ] ❌ Blocked (critical failures)

**Notes:**
_______________________________________________
_______________________________________________
_______________________________________________
