"""Reproduce: crash mid-write corrupts recovery state file.

Demonstrates that the current RecoveryStateManager.save() is not atomic —
a truncated write (simulating a crash) destroys all recovery progress.
Then shows that an atomic write (temp + fsync + rename) survives truncation.
"""

import json
import tempfile
from pathlib import Path

from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)


def make_large_state() -> RecoveryState:
    """Create a state with 200 graduated records to simulate real usage."""
    return RecoveryState(
        phase="reprompt",
        reprompt_attempt=1,
        graduated_results=[
            {"custom_id": f"rec_{i:04d}", "content": f'{{"value": {i}}}', "success": True}
            for i in range(200)
        ],
        evaluation_strategy_name="validation",
    )


def demonstrate_vulnerability():
    """Show that a truncated write corrupts the state file."""
    print("=" * 60)
    print("STEP 1: Demonstrate the vulnerability")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        state = make_large_state()

        # Save normally — works fine
        path = RecoveryStateManager.save(tmpdir, "test_action", state)
        loaded = RecoveryStateManager.load(tmpdir, "test_action")
        assert loaded is not None
        print(f"  Normal save: OK ({len(loaded.graduated_results)} graduated records)")

        # Read the full content to know its size
        full_content = path.read_text()
        full_size = len(full_content)
        print(f"  File size: {full_size} bytes")

        # Simulate crash: truncate the file mid-write
        truncated = full_content[: full_size // 3]
        with open(path, "w") as f:
            f.write(truncated)
        print(f"  Wrote truncated content: {len(truncated)} bytes (simulating crash)")

        # Attempt to load — returns None, all data lost
        loaded = RecoveryStateManager.load(tmpdir, "test_action")
        assert loaded is None, "Expected None from corrupted file"
        print("  Load after truncation: None (all 200 records LOST)")
        print()


def demonstrate_atomic_pattern():
    """Show that atomic writes (temp + fsync + rename) survive truncation."""
    print("=" * 60)
    print("STEP 2: Demonstrate atomic write pattern")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        state = make_large_state()
        target = Path(tmpdir) / "batch" / ".recovery_state_test_action.json"
        target.parent.mkdir(parents=True)

        # Write the initial good state
        data = state.to_dict()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"  Initial save: OK ({len(state.graduated_results)} graduated records)")

        # Now simulate an atomic write that gets interrupted:
        # The temp file gets truncated, but the original is untouched
        tmp_path = target.with_suffix(".json.tmp")
        full_json = json.dumps(data, ensure_ascii=False)
        truncated = full_json[: len(full_json) // 3]

        with open(tmp_path, "w") as f:
            f.write(truncated)
        # Crash happens here — rename never executes
        print(f"  Temp file truncated: {len(truncated)} bytes (simulating crash)")

        # The original file is still intact
        with open(target) as f:
            loaded_data = json.load(f)
        loaded = RecoveryState(**loaded_data)
        assert len(loaded.graduated_results) == 200
        print(
            f"  Original file intact: {len(loaded.graduated_results)} graduated records PRESERVED"
        )

        # Clean up temp file (in real code, try/finally does this)
        if tmp_path.exists():
            tmp_path.unlink()
        print("  Temp file cleaned up")
        print()


if __name__ == "__main__":
    print()
    demonstrate_vulnerability()
    demonstrate_atomic_pattern()
    print("=" * 60)
    print("CONCLUSION: Direct writes corrupt on crash.")
    print("Atomic writes (temp + fsync + rename) preserve data.")
    print("=" * 60)
