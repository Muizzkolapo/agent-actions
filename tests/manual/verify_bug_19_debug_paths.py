"""Verify that debugging guide database paths match the storage layer (bug #19).

Run: python tests/manual/verify_bug_19_debug_paths.py

Checks that the docs use the correct DB path (agent_io/store/<workflow>.db)
and do NOT reference the old wrong paths (.agent_actions.db, outputs.db).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEBUGGING_GUIDE = (
    ROOT
    / "agent_actions"
    / "skills"
    / "agent-actions-workflow"
    / "references"
    / "debugging-guide.md"
)
TROUBLESHOOTING = ROOT / "docs.agent-actions" / "docs" / "guides" / "troubleshooting.md"

passed = 0
failed = 0


def check(description: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if not condition:
        failed += 1
    else:
        passed += 1
    print(f"  [{status}] {description}")
    if detail:
        print(f"         {detail}")


print("=" * 60)
print("Bug #19: Verify debugging guide database paths are correct")
print("=" * 60)

# --- Check 1: What path does the storage layer actually use? ---
print("\n1. Actual database path in storage layer")
storage_init = ROOT / "agent_actions" / "storage" / "__init__.py"
source = storage_init.read_text()
match = re.search(r'db_path\s*=.*"store".*\.db', source)
check(
    "Storage layer uses agent_io/store/<name>.db",
    match is not None,
    f"Found: {match.group(0) if match else 'NOT FOUND'}",
)

# --- Check 2: debugging-guide.md uses correct path ---
print("\n2. Debugging guide uses correct database path")
guide_text = DEBUGGING_GUIDE.read_text()
check(
    "debugging-guide.md does NOT reference .agent_actions.db",
    ".agent_actions.db" not in guide_text,
)
check(
    "debugging-guide.md uses store/<workflow>.db",
    "agent_io/store/<workflow>.db" in guide_text,
)

# --- Check 3: troubleshooting.md uses correct path ---
print("\n3. Troubleshooting guide uses correct database path")
troubleshooting_text = TROUBLESHOOTING.read_text()
check(
    "troubleshooting.md does NOT reference outputs.db",
    "outputs.db" not in troubleshooting_text,
)
check(
    "troubleshooting.md uses store/ path",
    "agent_io/store/" in troubleshooting_text,
)

# --- Check 4: Prompt trace caveats present ---
print("\n4. Prompt trace caveats for tool actions")
check(
    "debugging-guide.md has tool action prompt trace caveat",
    "Tool actions have no prompt traces" in guide_text,
)
check(
    "troubleshooting.md has tool action prompt trace caveat",
    "Tool (UDF) actions do not generate prompt traces" in troubleshooting_text,
)

# --- Summary ---
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
if failed:
    print("Some checks failed — investigate before proceeding")
    sys.exit(1)
else:
    print("All checks passed — docs match codebase")
    sys.exit(0)
