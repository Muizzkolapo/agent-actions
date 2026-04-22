"""Reproduction script for tag_graduated type mismatch bug.

Bug: tag_graduated() replaces the typed RecoveryMetadata dataclass with a raw
dict, destroying retry/reprompt metadata.  _is_already_graduated() checks
isinstance(meta, dict) but RecoveryMetadata is a dataclass, so the guard
never fires.

Run:  python tests/manual/repro_bug_20_tag_graduated_type.py

Expected BEFORE fix: all three checks FAIL (bugs confirmed)
Expected AFTER fix:  all three checks PASS
"""

import sys

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.loop import EvaluationLoop
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

# --- Setup ---
# Create a BatchResult with real RecoveryMetadata including retry info
result = BatchResult(
    custom_id="r1",
    content={"answer": 42},
    success=True,
    recovery_metadata=RecoveryMetadata(
        retry=RetryMetadata(attempts=2, failures=1, succeeded=True, reason="timeout"),
    ),
)


# Create a minimal strategy mock
class FakeStrategy:
    name = "validation"
    max_attempts = 3
    on_exhausted = "keep"

    def evaluate(self, r):
        return True

    def build_feedback(self, r):
        return "fix it"


loop = EvaluationLoop(FakeStrategy())

failures = []

# --- Check 1: tag_graduated replaces RecoveryMetadata with raw dict ---
print("Check 1: tag_graduated preserves RecoveryMetadata type")
loop.tag_graduated([result])
if not isinstance(result.recovery_metadata, RecoveryMetadata):
    print(
        f"  FAIL: recovery_metadata is {type(result.recovery_metadata).__name__}, not RecoveryMetadata"
    )
    failures.append("type_replaced")
else:
    print("  PASS: recovery_metadata is still RecoveryMetadata")

# --- Check 2: retry metadata preserved ---
print("Check 2: retry metadata preserved after tag_graduated")
meta = result.recovery_metadata
if isinstance(meta, RecoveryMetadata):
    if meta.retry is None:
        print("  FAIL: retry metadata was destroyed")
        failures.append("retry_destroyed")
    elif meta.retry.attempts != 2:
        print(f"  FAIL: retry.attempts is {meta.retry.attempts}, expected 2")
        failures.append("retry_corrupted")
    else:
        print("  PASS: retry metadata preserved (attempts=2)")
else:
    # If type was replaced (check 1 failed), retry is definitely gone
    if isinstance(meta, dict) and "retry" not in meta:
        print("  FAIL: raw dict has no retry key — retry metadata destroyed")
        failures.append("retry_destroyed")
    else:
        print(f"  FAIL: unexpected metadata type: {type(meta)}")
        failures.append("retry_unknown")

# --- Check 3: _is_already_graduated detects tagged result ---
print("Check 3: _is_already_graduated detects tagged result")
# Re-create a fresh result, tag it, then check detection
fresh = BatchResult(
    custom_id="r2",
    content={"answer": 99},
    success=True,
    recovery_metadata=RecoveryMetadata(),
)
loop.tag_graduated([fresh])
detected = loop._is_already_graduated(fresh)
if not detected:
    print("  FAIL: _is_already_graduated returned False after tag_graduated")
    failures.append("detection_broken")
else:
    print("  PASS: _is_already_graduated correctly returns True")

# --- Summary ---
print()
if failures:
    print(f"RESULT: {len(failures)} bug(s) confirmed: {', '.join(failures)}")
    sys.exit(1)
else:
    print("RESULT: all checks passed — bug is fixed")
    sys.exit(0)
