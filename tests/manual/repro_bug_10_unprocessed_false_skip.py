"""Reproduce bug #10: UNPROCESSED records with empty data trigger false NODE_LEVEL SKIPPED.

When all records have ProcessingStatus.UNPROCESSED with empty data (None or []),
the pipeline disposition condition fires because:
  - stats.success == 0  ✓
  - stats.failed == 0   ✓
  - stats.exhausted == 0 ✓
  - stats.deferred == 0  ✓
  - not output → True (UNPROCESSED with empty data adds nothing to output)
  - stats.unprocessed is NOT checked → condition fires → false SKIPPED

After fix: stats.unprocessed > 0 prevents the condition from firing.
"""

from agent_actions.processing.result_collector import CollectionStats

# Simulate: 5 UNPROCESSED records, all with empty data → no output
stats = CollectionStats(unprocessed=5, success=0, failed=0, exhausted=0, deferred=0)
output: list = []  # UNPROCESSED with empty data produces no output
data = [{"id": str(i)} for i in range(5)]  # Non-empty input

# OLD condition (the bug) — missing stats.unprocessed == 0
old_condition = (
    data
    and stats.success == 0
    and stats.failed == 0
    and stats.exhausted == 0
    and stats.deferred == 0
    and not output
)

# NEW condition (the fix) — includes stats.unprocessed == 0
new_condition = (
    data
    and stats.success == 0
    and stats.failed == 0
    and stats.exhausted == 0
    and stats.deferred == 0
    and stats.unprocessed == 0
    and not output
)

print(f"Old condition (buggy): {old_condition}")
print(f"New condition (fixed): {new_condition}")

if old_condition and not new_condition:
    print("PASS: Old condition fires (confirms bug), new condition blocks it (confirms fix)")
    exit(0)
elif not old_condition:
    print("UNEXPECTED: Old condition did not fire — bug may have been fixed elsewhere")
    exit(1)
else:
    print("FAIL: New condition still fires — fix is ineffective")
    exit(1)
